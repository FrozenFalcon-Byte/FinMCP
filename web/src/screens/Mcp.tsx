/* MCP, live. The app is an MCP host: every screen reads and writes the ledger through its own MCP clients, and the
   server reaches back through sampling, elicitation and roots. This screen draws that architecture, streams the
   real protocol traffic, and lets you drive every primitive by hand. */
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Chip, ErrorBox, Icon, PageHead, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { todayIso } from "../lib/format";
import { KIND_LABEL, useFeed, type McpOverview, type McpSchema, type TraceEntry, type TraceStats } from "../lib/mcp";
import { useApi } from "../lib/useApi";

type Edge = "ui-web" | "ui-asst" | "web-srv" | "asst-srv" | "srv-db" | "ext-srv";
interface Pulse { id: number; edge: Edge; back: boolean; kind: string; delay: number }

const PATHS: Record<Edge, string> = {
  "ui-web": "M150 176 C 200 176, 220 118, 268 118",
  "ui-asst": "M150 204 C 200 204, 220 262, 268 262",
  "web-srv": "M428 118 C 480 118, 500 176, 548 176",
  "asst-srv": "M428 262 C 480 262, 500 204, 548 204",
  "srv-db": "M712 190 L 770 190",
  "ext-srv": "M630 330 L 630 238",
};

const MYSTERY = ["Kavya Pottery Studio", "Moss & Fern Co", "Tiny Tusk Traders", "Olive Loom Atelier"];

function edgesFor(e: TraceEntry): Edge[] {
  const client: "web" | "asst" = e.client.includes("assistant") ? "asst" : "web";
  const hop: Edge = client === "web" ? "web-srv" : "asst-srv";
  if (e.kind === "tool" || e.kind === "resource") return [hop, "srv-db"];
  return [hop];
}

function Diagram({ pulses, overview }: { pulses: Pulse[]; overview: McpOverview | null }) {
  const web = overview?.sessions[0];
  const sampling = web?.offers.includes("sampling");
  const hot = new Set(pulses.map((p) => p.edge));
  return (
    <svg className="arch" viewBox="0 0 880 370" role="img" aria-label="FinMCP architecture: this app hosts two MCP clients that talk to the FinMCP server, which owns the Postgres ledger; external MCP clients connect over HTTP.">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" className="arch-arrow" /></marker>
      </defs>
      <rect x="236" y="40" width="226" height="286" rx="22" className="arch-host" />
      <text x="349" y="64" className="arch-cap" textAnchor="middle">MCP HOST · FastAPI</text>
      {Object.entries(PATHS).map(([k, d]) => <path key={k} d={d} className={`arch-edge ${k === "ext-srv" ? "dashed" : ""} ${hot.has(k as Edge) ? "on" : ""}`} markerEnd="url(#arr)" />)}
      <g className="arch-node"><rect x="20" y="150" width="130" height="80" rx="18" /><text x="85" y="186" textAnchor="middle" className="t">You</text><text x="85" y="206" textAnchor="middle" className="s">screens · Ask</text></g>
      <g className="arch-node client"><rect x="268" y="84" width="160" height="68" rx="16" /><text x="348" y="113" textAnchor="middle" className="t">finmcp-web</text><text x="348" y="133" textAnchor="middle" className="s">elicitation · roots{sampling ? " · sampling" : ""}</text></g>
      <g className="arch-node client alt"><rect x="268" y="228" width="160" height="68" rx="16" /><text x="348" y="257" textAnchor="middle" className="t">finmcp-assistant</text><text x="348" y="277" textAnchor="middle" className="s">model tool loop</text></g>
      <g className="arch-node core"><rect x="548" y="120" width="164" height="118" rx="20" /><text x="630" y="152" textAnchor="middle" className="t">FinMCP server</text>
        <text x="630" y="176" textAnchor="middle" className="s">27 tools · 13 resources</text><text x="630" y="194" textAnchor="middle" className="s">4 prompts · completions</text><text x="630" y="212" textAnchor="middle" className="s">subscriptions/listen</text></g>
      <g className="arch-node"><rect x="770" y="158" width="96" height="64" rx="16" /><text x="818" y="186" textAnchor="middle" className="t">Postgres</text><text x="818" y="204" textAnchor="middle" className="s">row-level security</text></g>
      <g className="arch-node ghost"><rect x="552" y="330" width="156" height="34" rx="12" /><text x="630" y="352" textAnchor="middle" className="s">Claude Desktop · Cursor · CLI</text></g>
      <text x="642" y="290" className="arch-cap">/mcp · bearer token</text>
      {/* Each message is a short streak of light that runs the length of its edge (normalised with pathLength=1). */}
      {pulses.map((p) => (
        <motion.path key={p.id} d={PATHS[p.edge]} pathLength={1} className={`arch-comet k-${p.kind}`} strokeDasharray="0.16 1.4"
          initial={{ strokeDashoffset: p.back ? -1 : 0.16, opacity: 0 }} animate={{ strokeDashoffset: p.back ? 0.16 : -1, opacity: [0, 1, 1, 0] }}
          transition={{ duration: 0.9, delay: p.delay, ease: [0.45, 0, 0.25, 1], opacity: { duration: 0.9, delay: p.delay, times: [0, 0.12, 0.8, 1] } }} />
      ))}
    </svg>
  );
}

const CAPS: { kind: string; title: string; side: "client" | "server"; body: string }[] = [
  { kind: "elicitation", side: "client", title: "Elicitation", body: "When a guess is weak, the server pauses the tool call and asks you where the money belongs. Deletes ask for confirmation." },
  { kind: "sampling", side: "client", title: "Sampling", body: "Merchants no rule knows are sent to this app's model in one batched round trip. The server never holds an API key." },
  { kind: "roots", side: "client", title: "Roots", body: "The server asks which folders it may read and refuses any statement outside your upload folder." },
  { kind: "subscription", side: "server", title: "Subscriptions", body: "The app keeps a subscriptions/listen stream open. Any client's write, even Claude Desktop's, refreshes these screens." },
  { kind: "progress", side: "server", title: "Progress & logging", body: "Imports and bulk categorising report progress, and the server narrates what it filed and why." },
  { kind: "completion", side: "server", title: "Completion", body: "Prompt and resource-template arguments autocomplete, the same way Claude Desktop fills them." },
];

function Completion() {
  const [value, setValue] = useState("2026-");
  const [values, setValues] = useState<string[]>([]);
  useEffect(() => {
    const t = window.setTimeout(() => {
      api.get<{ values: string[] }>("/mcp/complete", { ref: "resource", name: "finmcp://transactions/{month}", argument: "month", value })
        .then((r) => setValues(r.values.slice(0, 6))).catch(() => setValues([]));
    }, 200);
    return () => window.clearTimeout(t);
  }, [value]);
  return (
    <div className="cap-try">
      <input className="input mono" value={value} onChange={(e) => setValue(e.target.value)} aria-label="Month to complete" />
      <div className="chips">{values.map((v) => <Chip key={v} tone="outline" onClick={() => setValue(v)}>{v}</Chip>)}</div>
    </div>
  );
}

function Playground({ schema }: { schema: McpSchema | null }) {
  const [tab, setTab] = useState<"tools" | "resources" | "prompts">("tools");
  const [tool, setTool] = useState("get_summary");
  const [args, setArgs] = useState('{\n  "period": "this month"\n}');
  const [uri, setUri] = useState("finmcp://overview");
  const [prompt, setPrompt] = useState("monthly_spending_review");
  const [pargs, setPargs] = useState<Record<string, string>>({});
  const [out, setOut] = useState<{ ok: boolean; body: string; ms?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const def = schema?.tools.find((t) => t.name === tool);
  const pdef = schema?.prompts.find((p) => p.name === prompt);

  const pickTool = (name: string) => {
    setTool(name);
    const t = schema?.tools.find((x) => x.name === name);
    const example: Record<string, unknown> = {};
    for (const k of t?.input_schema.required ?? []) {
      const p = t?.input_schema.properties?.[k];
      example[k] = p?.type === "integer" || p?.type === "number" ? 1 : k === "date" ? todayIso() : "";
    }
    setArgs(JSON.stringify(example, null, 2));
  };

  const run = async () => {
    setBusy(true);
    setOut(null);
    try {
      if (tab === "tools") {
        const r = await api.post<{ ok: boolean; data: unknown; text: string | null; ms: number }>("/mcp/call", { name: tool, arguments: JSON.parse(args || "{}") });
        setOut({ ok: r.ok, body: r.data !== null && r.data !== undefined ? JSON.stringify(r.data, null, 2) : r.text ?? "", ms: r.ms });
      } else if (tab === "resources") {
        const r = await api.get<{ text: string }>("/mcp/read", { uri });
        let body = r.text;
        try { body = JSON.stringify(JSON.parse(r.text), null, 2); } catch { /* not JSON */ }
        setOut({ ok: true, body });
      } else {
        const r = await api.post<{ text: string }>("/mcp/prompt", { name: prompt, arguments: pargs });
        setOut({ ok: true, body: r.text });
      }
    } catch (e) {
      setOut({ ok: false, body: e instanceof Error ? e.message : String(e) });
    }
    setBusy(false);
  };

  if (!schema) return <Skeleton h={220} />;
  return (
    <div className="card play" id="playground">
      <div className="card-head">
        <h3>Playground</h3>
        <div className="tabs">
          {(["tools", "resources", "prompts"] as const).map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => { setTab(t); setOut(null); }}>{t}</button>)}
        </div>
      </div>
      <div className="play-grid">
        <div className="stack">
          {tab === "tools" && (<>
            <select className="input" value={tool} onChange={(e) => pickTool(e.target.value)}>
              {schema.tools.map((t) => <option key={t.name} value={t.name}>{t.name}{t.annotations.readOnlyHint ? "" : t.annotations.destructiveHint ? "  ·  destructive" : "  ·  writes"}</option>)}
            </select>
            <p className="small muted">{def?.description}</p>
            <textarea className="input mono" rows={7} value={args} onChange={(e) => setArgs(e.target.value)} spellCheck={false} aria-label="Tool arguments (JSON)" />
          </>)}
          {tab === "resources" && (<>
            <select className="input" value={uri} onChange={(e) => setUri(e.target.value)}>
              {schema.resources.map((r) => <option key={r.uri} value={r.uri}>{r.uri}</option>)}
              <option value={`finmcp://transactions/${todayIso().slice(0, 7)}`}>finmcp://transactions/{"{month}"} (template)</option>
            </select>
            <input className="input mono" value={uri} onChange={(e) => setUri(e.target.value)} aria-label="Resource URI" />
            <p className="small muted">{schema.resources.find((r) => r.uri === uri)?.description ?? schema.templates[0]?.description}</p>
          </>)}
          {tab === "prompts" && (<>
            <select className="input" value={prompt} onChange={(e) => { setPrompt(e.target.value); setPargs({}); }}>
              {schema.prompts.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
            <p className="small muted">{pdef?.description}</p>
            {pdef?.arguments.map((a) => (
              <label key={a.name} className="field"><span>{a.name}{a.required ? " *" : ""}</span>
                <input className="input mono" value={pargs[a.name] ?? ""} placeholder={a.description ?? ""} onChange={(e) => setPargs((s) => ({ ...s, [a.name]: e.target.value }))} />
              </label>
            ))}
          </>)}
          <button className="btn primary" onClick={run} disabled={busy}>{busy ? <Spinner /> : <Icon name="send" />} {tab === "tools" ? "tools/call" : tab === "resources" ? "resources/read" : "prompts/get"}</button>
        </div>
        <pre className={`play-out ${out && !out.ok ? "err" : ""}`}>{out ? out.body : "Results show here. Every call goes through the app's real MCP client, so it also appears in the trace."}{out?.ms !== undefined ? `\n\n· ${out.ms} ms` : ""}</pre>
      </div>
    </div>
  );
}

export default function Mcp() {
  const toast = useToast();
  const overview = useApi(() => api.get<McpOverview>("/mcp/overview"), [], { live: false });
  const schema = useApi(() => api.get<McpSchema>("/mcp/schema"), [], { live: false });
  const [entries, setEntries] = useState<TraceEntry[]>([]);
  const [stats, setStats] = useState<TraceStats | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [paused, setPaused] = useState(false);
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const [updates, setUpdates] = useState<{ uri: string; at: number }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const pid = useRef(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    api.get<{ entries: TraceEntry[]; stats: TraceStats }>("/mcp/trace", { limit: 150 }).then((r) => { setEntries(r.entries.reverse()); setStats(r.stats); }).catch(() => {});
  }, []);

  useFeed((ev) => {
    if (ev.type === "change" && ev.uri) setUpdates((u) => [{ uri: ev.uri as string, at: Date.now() }, ...u.filter((x) => x.uri !== ev.uri)].slice(0, 6));
    if (ev.type !== "mcp" || typeof ev.seq !== "number") return;
    const e = ev as unknown as TraceEntry;
    setStats((s) => s && { ...s, total: e.seq, by_kind: { ...s.by_kind, [e.kind]: (s.by_kind[e.kind] ?? 0) + 1 }, by_method: { ...s.by_method, [e.method]: (s.by_method[e.method] ?? 0) + 1 } });
    if (!pausedRef.current) setEntries((xs) => [e, ...xs].slice(0, 200));
    // One message travels hop by hop: you → client → server → database (or back the other way), each leg after the last.
    const back = e.dir === "in";
    const legs: { edge: Edge; back: boolean }[] = edgesFor(e).map((edge) => ({ edge, back }));
    if (e.client.includes("assistant") && e.kind === "tool") legs.unshift({ edge: "ui-asst", back: false });
    else if (e.kind === "tool" || e.kind === "resource") legs.unshift({ edge: "ui-web", back: false });
    if (back) legs.reverse();
    const fresh: Pulse[] = legs.map((l, i) => ({ id: ++pid.current, ...l, kind: e.kind, delay: i * 0.3 }));
    setPulses((ps) => [...ps, ...fresh].slice(-24));
    window.setTimeout(() => setPulses((ps) => ps.filter((p) => !fresh.includes(p))), 1000 + fresh.length * 300);
  });

  // Opened from a landing-page card (/app/mcp#sampling): bring that primitive into view and light it up once.
  const ready = !!overview.data && !!schema.data;
  useEffect(() => {
    const id = window.location.hash.slice(1);
    const el = ready && id ? document.getElementById(id) : null;
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash");
  }, [ready]);

  const kinds = useMemo(() => Object.keys(KIND_LABEL).filter((k) => (stats?.by_kind[k] ?? 0) > 0), [stats]);
  const shown = filter === "all" ? entries : entries.filter((e) => e.kind === filter);
  const web = overview.data?.sessions[0];
  const offered = (k: string) => (k === "elicitation" || k === "sampling" || k === "roots" ? web?.offers.includes(k) : true);

  /* The demos run a real tool call, so what comes back is what a connected client would see. A failed call carries
     the server's own message: hiding it behind "the call failed" is how a working boundary reads as a broken app. */
  const tryIt = async (kind: string) => {
    setBusy(kind);
    try {
      if (kind === "elicitation") {
        const merchant = MYSTERY[Math.floor(Math.random() * MYSTERY.length)];
        const r = await api.post<{ ok: boolean; text: string | null; data: { transaction: { category: string | null }; asked: string | null } }>("/mcp/call", {
          name: "add_transaction", arguments: { date: todayIso(), amount: 349, merchant, description: "demo purchase from the MCP screen" } });
        toast(r.ok ? `${merchant}: ${r.data.transaction.category ?? "left uncategorised"} (${r.data.asked ?? "not asked"})` : r.text ?? "The call failed.", r.ok ? "ok" : "err");
      } else if (kind === "sampling") {
        const r = await api.post<{ ok: boolean; text: string | null; data: { processed: number; categorized: number; provider: string } }>("/mcp/call", { name: "categorize_uncategorized", arguments: { limit: 20 } });
        if (!r.ok) toast(r.text ?? "The call failed.", "err");
        // Nothing uncategorised means nothing to ask the model about, so no sampling round happens at all.
        else if (r.data.processed === 0) toast("Nothing uncategorised right now — add one with an unfamiliar merchant, then run this again.");
        else toast(`${r.data.categorized} of ${r.data.processed} filed via ${r.data.provider}`);
      } else if (kind === "roots") {
        const r = await api.post<{ ok: boolean; text: string | null }>("/mcp/call", { name: "parse_statement", arguments: { file_path: "/etc/hosts" } });
        // Being turned away IS the demo: the server asked this client for its roots and honoured the answer.
        toast(r.ok ? "Unexpected: /etc/hosts was read, so this client declared no roots." : "Refused, as it should be: /etc/hosts is outside this client's roots.", r.ok ? "err" : "ok");
      } else if (kind === "progress") {
        const r = await api.post<{ ok: boolean; text: string | null; data: { processed: number } }>("/mcp/call", { name: "categorize_uncategorized", arguments: { limit: 5 } });
        if (!r.ok) toast(r.text ?? "The call failed.", "err");
        else toast(r.data.processed ? "Watch the progress notifications in the trace." : "Nothing to work through, so there was no progress to report.");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "err");
    }
    setBusy(null);
  };

  return (
    <div className="page mcp-page">
      <PageHead title="MCP, live" sub="This app is an MCP host. Every screen reads and writes your ledger through its own MCP clients, and the server talks back.">
        <Link className="btn sm" to="/app/connect"><Icon name="plug" /> Connect other apps</Link>
      </PageHead>

      {overview.error && <ErrorBox>{overview.error}</ErrorBox>}

      <div className="card arch-card">
        <Diagram pulses={pulses} overview={overview.data} />
        <div className="arch-stats">
          <div><b>{stats?.total ?? "·"}</b><span>messages</span></div>
          <div><b>{stats?.by_method["tools/call"] ?? 0}</b><span>tool calls</span></div>
          <div><b>{stats?.by_kind.elicitation ?? 0}</b><span>questions asked</span></div>
          <div><b>{stats?.by_method["notifications/resources/updated"] ?? 0}</b><span>live updates</span></div>
          <div><b>{web?.protocol ?? "·"}</b><span>protocol</span></div>
        </div>
      </div>

      <div className="caps">
        {CAPS.map((c) => (
          <div key={c.kind} id={c.kind} className={`card cap ${offered(c.kind) ? "" : "off"}`}>
            <div className="cap-head">
              <span className={`cap-dot k-${c.kind}`} />
              <h3>{c.title}</h3>
              <span className="micro muted">{c.side === "client" ? "client → server" : "server → client"}</span>
              <span className="grow" />
              <b className="cap-n">{c.kind === "progress" ? (stats?.by_kind.progress ?? 0) + (stats?.by_kind.log ?? 0) : stats?.by_kind[c.kind] ?? 0}</b>
            </div>
            <p className="small muted">{c.body}</p>
            {c.kind === "sampling" && !offered("sampling") && <p className="micro muted">Off: no model configured (ANTHROPIC_API_KEY or OPENROUTER_API_KEY), so the server falls back to its own rules.</p>}
            {c.kind === "completion" && <Completion />}
            {c.kind === "subscription" && (
              <div className="cap-try updates">{updates.length ? updates.map((u) => <span key={u.uri} className="mono micro">{u.uri.replace("finmcp://", "")}</span>) : <span className="micro muted">Listening to {overview.data?.subscribed.length ?? 11} resources…</span>}</div>
            )}
            {["elicitation", "sampling", "roots", "progress"].includes(c.kind) && (
              <button className="btn sm" disabled={busy !== null} onClick={() => tryIt(c.kind)}>
                {busy === c.kind ? <Spinner /> : <Icon name="bolt" />}
                {c.kind === "elicitation" ? "Add a mystery ₹349 purchase" : c.kind === "sampling" ? "Categorise what's left" : c.kind === "roots" ? "Try to read a file outside the roots" : "Run a bulk job"}
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="card trace">
        <div className="card-head">
          <h3>Protocol trace</h3>
          <span className="grow" />
          <button className="btn ghost sm" onClick={() => setPaused((p) => !p)}>{paused ? "Resume" : "Pause"}</button>
        </div>
        <div className="chips">
          <Chip on={filter === "all"} onClick={() => setFilter("all")}>All</Chip>
          {kinds.map((k) => <Chip key={k} on={filter === k} onClick={() => setFilter(k)}>{KIND_LABEL[k]} · {stats?.by_kind[k]}</Chip>)}
        </div>
        <div className="trace-list" role="log" aria-live="polite">
          {shown.length === 0 && <p className="small muted">Nothing yet. Use any screen, or the buttons above.</p>}
          {shown.map((e) => (
            <div key={e.seq} className={`trace-row ${e.ok ? "" : "bad"}`}>
              <span className="mono micro muted">{e.ts.slice(11, 19)}</span>
              <span className={`dir ${e.dir}`} title={e.dir === "in" ? "server → client" : "client → server"}>{e.dir === "in" ? "←" : "→"}</span>
              <span className={`kind k-${e.kind}`}>{e.method}</span>
              <span className="who micro">{e.client.replace("finmcp-", "")}</span>
              <span className="what small">{e.detail}</span>
              <span className="mono micro muted">{e.ms !== null && e.ms !== undefined ? `${e.ms} ms` : ""}</span>
            </div>
          ))}
        </div>
      </div>

      <Playground schema={schema.data} />
    </div>
  );
}
