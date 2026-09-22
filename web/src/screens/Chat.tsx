/* Ask: a conversation, laid out as one.

   The page is a fixed frame — the thread is the only thing that scrolls, and the composer sits at the bottom of
   that frame rather than sliding around the page. Everything lines up on one reading column, so a question, its
   answer and the box you typed it in share an edge. */
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ToolTrace } from "../components/ToolTrace";
import { useIsland, useToast } from "../components/Toast";
import { Icon, PageHead } from "../components/ui";
import { api, streamChat } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Markdown } from "../lib/markdown";
import type { Alerts, ChatEvent, ChatMessage, PromptInfo, ToolTraceItem } from "../lib/types";

const SUGGESTIONS = [
  "How am I doing this month?",
  "Which budgets am I about to blow?",
  "What subscriptions am I paying for?",
  "Top 5 merchants in the last 30 days",
  "How much did I spend on food last month vs this month?",
  "Show my uncategorized transactions and suggest categories",
];

const EASE = [0.22, 1, 0.36, 1] as const;
const RISE = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.34, ease: EASE },
};

let seq = 0;
const nid = () => `m${++seq}`;

function hello(name: string | undefined): string {
  const h = new Date().getHours();
  const first = (name ?? "").trim().split(" ")[0];
  const when = h < 5 ? "Still up" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  return first ? `${when}, ${first}` : when;
}

export default function Chat() {
  const { user } = useAuth();
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

  /* Follow the answer as it streams, but only while the reader is at the bottom: yanking the view down while
     someone is scrolled up reading an earlier answer is the rudest thing a chat can do. */
  const stick = useRef(true);
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const read = () => { stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; };
    el.addEventListener("scroll", read, { passive: true });
    return () => el.removeEventListener("scroll", read);
  }, []);
  useLayoutEffect(() => {
    const el = threadRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
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

  const empty = !messages.length;

  return (
    <div className="chat">
      <PageHead title="Ask" sub="Questions in plain language, answered from your own ledger.">
        <button className="btn sm" onClick={reset} disabled={empty}><Icon name="refresh" />New conversation</button>
      </PageHead>

      <div className="thread" ref={threadRef}>
        <div className="thread-in">
          <AnimatePresence initial={false} mode="popLayout">
            {empty ? (
              <motion.div key="blank" className="ask-blank" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.28, ease: EASE }}>
                <motion.div className="ask-hi" {...RISE}>
                  <span className="ask-orb"><Icon name="spark" /></span>
                  <h2>{hello(user?.name)}</h2>
                  <p>Ask about a month, a merchant, a budget — anything in your ledger. Every answer shows the tool calls behind it.</p>
                </motion.div>

                {nudge ? (
                  <motion.button type="button" className="ask-nudge" {...RISE} transition={{ ...RISE.transition, delay: 0.06 }}
                    onClick={() => void send(`I have these budget alerts: ${nudge.alerts.map((a) => a.message).join(" ")} Look at the transactions behind them and tell me the two most effective things I could cut this month.`)}>
                    <span className="ic"><Icon name="alert" /></span>
                    <span className="b">
                      <strong>{nudge.alert_count} budget {nudge.alert_count === 1 ? "alert" : "alerts"} for {nudge.label}</strong>
                      <span>{nudge.alerts.slice(0, 2).map((a) => a.message).join(" ")}</span>
                    </span>
                    <span className="go">Ask what to cut<Icon name="arrowRight" /></span>
                  </motion.button>
                ) : null}

                <div className="ask-picks">
                  {SUGGESTIONS.map((q, i) => (
                    <motion.button key={q} type="button" onClick={() => void send(q)}
                      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, ease: EASE, delay: 0.1 + i * 0.035 }}
                      whileHover={{ y: -2 }} whileTap={{ scale: 0.98 }}>
                      {q}<Icon name="arrowRight" />
                    </motion.button>
                  ))}
                </div>

                {prompts.length ? (
                  <motion.div className="ask-prompts" {...RISE} transition={{ ...RISE.transition, delay: 0.3 }}>
                    <div className="eyebrow">Server prompts</div>
                    <div className="suggest">
                      {prompts.map((p) => <button key={p.name} title={p.description ?? ""} onClick={() => void usePrompt(p)}><Icon name="wand" />{p.title}</button>)}
                    </div>
                  </motion.div>
                ) : null}
              </motion.div>
            ) : (
              messages.map((m) => (
                <motion.div className={`msg ${m.role}`} key={m.id} layout="position"
                  initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  transition={{ duration: 0.3, ease: EASE }}>
                  <div className="avatar">{m.role === "user" ? "you" : <Icon name="spark" />}</div>
                  <div className="body">
                    <ToolTrace items={m.trace} />
                    {m.role === "user" ? <div className="text">{m.text}</div> : (
                      <div className="text">
                        {m.text ? <Markdown text={m.text} /> : m.pending ? <span className="dots" aria-label="Thinking"><i /><i /><i /></span> : null}
                        {m.text && m.pending ? <span className="caret" /> : null}
                      </div>
                    )}
                    {m.error ? <div className="error-box">{m.error}</div> : null}
                    {m.usage ? <div className="small muted mono">{m.usage.input_tokens ?? 0} in · {m.usage.output_tokens ?? 0} out{m.usage.cache_read_input_tokens ? ` · ${m.usage.cache_read_input_tokens} cached` : ""}</div> : null}
                  </div>
                </motion.div>
              ))
            )}
          </AnimatePresence>
        </div>
      </div>

      <div className="composer">
        <div className="composer-in">
          <div className="box">
            <textarea id="chat-input" className="textarea" rows={1} placeholder="Ask about spending, budgets, or a merchant…" title="Enter to send, Shift+Enter for a new line" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={busy} />
            <AnimatePresence mode="wait" initial={false}>
              {busy ? (
                <motion.button key="stop" className="btn icon send" onClick={stop} aria-label="Stop"
                  initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} transition={{ duration: 0.14 }}>
                  <Icon name="x" />
                </motion.button>
              ) : (
                <motion.button key="send" className="btn icon primary send" onClick={() => void send(input)} disabled={!input.trim()} aria-label="Send"
                  initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }} transition={{ duration: 0.14 }}>
                  <Icon name="send" />
                </motion.button>
              )}
            </AnimatePresence>
          </div>
          <div className="composer-note">Enter sends · Shift + Enter for a new line</div>
        </div>
      </div>
    </div>
  );
}
