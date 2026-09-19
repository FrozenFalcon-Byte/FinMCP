import { useCallback, useEffect, useRef, useState } from "react";
import { ToolTrace } from "../components/ToolTrace";
import { useIsland, useToast } from "../components/Toast";
import { Icon, PageHead } from "../components/ui";
import { api, streamChat } from "../lib/api";
import { Markdown } from "../lib/markdown";
import { useStatus } from "../lib/status";
import type { Alerts, ChatEvent, ChatMessage, PromptInfo, ToolTraceItem } from "../lib/types";

const SUGGESTIONS = [
  "How am I doing this month?",
  "Which budgets am I about to blow?",
  "What subscriptions am I paying for?",
  "Top 5 merchants in the last 30 days",
  "How much did I spend on food last month vs this month?",
  "Show my uncategorized transactions and suggest categories",
];

let seq = 0;
const nid = () => `m${++seq}`;

export default function Chat() {
  const { health } = useStatus();
  const toast = useToast();
  const island = useIsland();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [prompts, setPrompts] = useState<PromptInfo[]>([]);
  const [nudge, setNudge] = useState<Alerts | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api.get<PromptInfo[]>("/prompts").then(setPrompts).catch(() => setPrompts([]));
    api.get<Alerts>("/alerts").then((a) => setNudge(a.alert_count ? a : null)).catch(() => setNudge(null));
  }, []);

  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const patchLast = useCallback((fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((ms) => {
      if (!ms.length) return ms;
      const copy = ms.slice();
      copy[copy.length - 1] = fn(copy[copy.length - 1]);
      return copy;
    });
  }, []);

  const send = useCallback(async (text: string) => {
    const msg = text.trim();
    if (!msg || busy) return;
    setInput("");
    setBusy(true);
    setMessages((ms) => [...ms, { id: nid(), role: "user", text: msg, trace: [] }, { id: nid(), role: "assistant", text: "", trace: [], pending: true }]);
    const controller = new AbortController();
    abortRef.current = controller;
    const started = Date.now();
    island.activity({ label: "Thinking", href: "/app/ask" });
    let writing = false;
    const onEvent = (ev: ChatEvent) => {
      switch (ev.type) {
        case "conversation": setConversationId(ev.conversation_id); break;
        case "text_delta":
          if (!writing) { writing = true; island.activity({ label: "Writing", href: "/app/ask" }); }
          patchLast((m) => ({ ...m, text: m.text + ev.text }));
          break;
        case "tool_call":
          writing = false;
          island.activity({ label: ev.name.replace(/_/g, " "), href: "/app/ask" });
          patchLast((m) => ({ ...m, trace: [...m.trace, { id: ev.id, name: ev.name, input: ev.input } as ToolTraceItem] }));
          break;
        case "tool_result": patchLast((m) => ({ ...m, trace: m.trace.map((t) => (t.id === ev.id ? { ...t, ok: ev.ok, preview: ev.preview, elapsed_ms: ev.elapsed_ms, data: ev.data } : t)) })); break;
        case "error": patchLast((m) => ({ ...m, error: ev.message })); break;
        case "done": patchLast((m) => ({ ...m, pending: false, usage: ev.usage, text: m.text || ev.text })); break;
        default: break;
      }
    };
    try {
      await streamChat(msg, conversationId, onEvent, controller.signal);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (!controller.signal.aborted) {
        patchLast((m) => ({ ...m, pending: false, error: message }));
        toast(message, "err");
      }
    } finally {
      patchLast((m) => ({ ...m, pending: false }));
      island.activity(null, controller.signal.aborted ? undefined : `Answered · ${Math.round((Date.now() - started) / 1000)}s`);
      setBusy(false);
      abortRef.current = null;
    }
  }, [busy, conversationId, patchLast, toast, island]);

  const stop = () => abortRef.current?.abort();
  const reset = async () => {
    if (conversationId) await api.del(`/chat/${conversationId}`).catch(() => undefined);
    setConversationId(null);
    setMessages([]);
  };
  const usePrompt = async (p: PromptInfo) => {
    try {
      const args: Record<string, string> = {};
      for (const a of p.arguments) {
        const v = window.prompt(`${p.title}: ${a.name}${a.required ? " (required)" : ""}`, "");
        if (v === null) return;
        if (v) args[a.name] = v;
      }
      const r = await api.post<{ text: string }>(`/prompts/${p.name}`, { arguments: args });
      setInput(r.text);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); }
  };

  return (
    <>
      <PageHead title="Ask" sub={conversationId ? "The assistant calls the same MCP tools the app uses; expand a step to see the call." : "Ask anything about your money. The assistant picks the MCP tools."}>
        <button className="btn sm" onClick={reset} disabled={!messages.length}><Icon name="refresh" />New conversation</button>
      </PageHead>
      <div className="chat">
        <div className="thread" ref={threadRef}>
          {!messages.length ? (
            <div className="stack" style={{ maxWidth: 760 }}>
              {nudge ? (
                <div className="msg assistant">
                  <div className="avatar"><Icon name="spark" /></div>
                  <div className="body">
                    <div className="text">
                      <p><strong>Heads up.</strong> {nudge.alert_count} budget {nudge.alert_count === 1 ? "alert" : "alerts"} for {nudge.label}:</p>
                      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{nudge.alerts.map((a) => <li key={a.category}>{a.message}</li>)}</ul>
                    </div>
                    <div><button className="btn sm" onClick={() => void send(`I have these budget alerts: ${nudge.alerts.map((a) => a.message).join(" ")} Look at the transactions behind them and tell me the two most effective things I could cut this month.`)}>Ask what to cut</button></div>
                  </div>
                </div>
              ) : null}
              <div className="card">
                <div className="card-head"><h2>Try asking</h2><span className="meta">{health?.driver === "anthropic" ? "answered by Claude with FinMCP tools" : health?.driver === "openrouter" ? `answered by ${(health.model ?? "the model").split("/").pop()} with FinMCP tools` : "offline engine: one tool call per question"}</span></div>
                <div className="suggest">{SUGGESTIONS.map((s) => <button key={s} onClick={() => void send(s)}>{s}</button>)}</div>
                {prompts.length ? (
                  <>
                    <div className="eyebrow" style={{ marginTop: 14, marginBottom: 6 }}>Server prompts</div>
                    <div className="suggest">{prompts.map((p) => <button key={p.name} title={p.description ?? ""} onClick={() => void usePrompt(p)}><Icon name="wand" /> {p.title}</button>)}</div>
                  </>
                ) : null}
              </div>
            </div>
          ) : null}
          {messages.map((m) => (
            <div className={`msg ${m.role}`} key={m.id}>
              <div className="avatar">{m.role === "user" ? "you" : <Icon name="spark" />}</div>
              <div className="body">
                <ToolTrace items={m.trace} />
                {m.role === "user" ? <div className="text">{m.text}</div> : (
                  <div className={`text ${m.pending ? "cursor" : ""}`}>
                    {m.text ? <Markdown text={m.text} /> : m.pending ? <span className="muted">thinking…</span> : null}
                  </div>
                )}
                {m.error ? <div className="error-box">{m.error}</div> : null}
                {m.usage ? <div className="small muted mono">{m.usage.input_tokens ?? 0} in · {m.usage.output_tokens ?? 0} out{m.usage.cache_read_input_tokens ? ` · ${m.usage.cache_read_input_tokens} cached` : ""}</div> : null}
              </div>
            </div>
          ))}
        </div>
        <div className="composer">
          <div className="box">
            <textarea id="chat-input" className="textarea" rows={2} placeholder="Ask about spending, budgets, or a merchant…" title="Enter to send, Shift+Enter for a new line" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={busy} />
            {busy ? <button className="btn" onClick={stop}><Icon name="x" />Stop</button> : <button className="btn primary" onClick={() => void send(input)} disabled={!input.trim()}><Icon name="send" />Send</button>}
          </div>
        </div>
      </div>
    </>
  );
}
