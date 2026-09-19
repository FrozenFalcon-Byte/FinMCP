import { useState } from "react";
import { useToast } from "../components/Toast";
import { Chip, ClientPill, Empty, ErrorBox, Icon, PageHead, Sheet, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { relTime } from "../lib/format";
import { useLedger } from "../lib/ledger";
import type { Activity, McpCatalog, McpToken } from "../lib/types";
import { useApi } from "../lib/useApi";

type Client = "claude-desktop" | "claude-code" | "cursor" | "generic" | "stdio";
const CLIENTS: { id: Client; label: string }[] = [
  { id: "claude-desktop", label: "Claude Desktop" },
  { id: "claude-code", label: "Claude Code" },
  { id: "cursor", label: "Cursor" },
  { id: "generic", label: "Any MCP client" },
  { id: "stdio", label: "Local process" },
];

export function snippet(client: Client, endpoint: string, token: string): string {
  const t = token || "fm_YOUR_TOKEN";
  switch (client) {
    case "claude-desktop":
      return JSON.stringify({ mcpServers: { finmcp: { command: "npx", args: ["-y", "mcp-remote", endpoint, "--header", `Authorization: Bearer ${t}`] } } }, null, 2);
    case "claude-code":
      return `claude mcp add --transport http finmcp ${endpoint} --header "Authorization: Bearer ${t}"`;
    case "cursor":
      return JSON.stringify({ mcpServers: { finmcp: { url: endpoint, headers: { Authorization: `Bearer ${t}` } } } }, null, 2);
    case "stdio":
      return JSON.stringify({ mcpServers: { finmcp: { command: "/path/to/FinTrack/.venv/bin/python", args: ["-m", "finmcp", "--token", t, "--client", "Claude Desktop"], env: { PYTHONPATH: "/path/to/FinTrack" } } } }, null, 2);
    default:
      return `POST ${endpoint}\nAuthorization: Bearer ${t}\nAccept: application/json, text/event-stream\nContent-Type: application/json\n\n{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"my-client","version":"1.0"}}}`;
  }
}

export const NOTES: Record<Client, string> = {
  "claude-desktop": "Settings → Developer → Edit Config, paste into claude_desktop_config.json, restart Claude Desktop. Needs Node (npx).",
  "claude-code": "Run once in a terminal. Then ask Claude Code about your money from any project.",
  cursor: "Cursor Settings → MCP → Add new global MCP server, paste into mcp.json.",
  generic: "Streamable HTTP transport. Send the bearer token on every request; the session id comes back in the mcp-session-id header.",
  stdio: "Runs the server as a local process that talks straight to the database. Handy when the API is not running.",
};

export default function Connect() {
  const { config } = useAuth();
  const { version } = useLedger();
  const toast = useToast();
  const tokens = useApi(() => api.get<McpToken[]>("/mcp/tokens"), [], { live: false });
  const catalog = useApi(() => api.get<McpCatalog>("/mcp/catalog"), [], { live: false });
  const activity = useApi(() => api.get<Activity>("/activity", { limit: 1 }), [version]);
  const [client, setClient] = useState<Client>("claude-desktop");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("Claude Desktop");
  const [fresh, setFresh] = useState<{ token: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const endpoint = catalog.data?.endpoint ?? config?.mcp_endpoint ?? `${window.location.origin}/mcp`;

  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast("Copied."); } catch { toast("Copy failed; select the text instead.", "err"); }
  };
  const create = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ token: string; record: McpToken }>("/mcp/tokens", { name: name.trim() || "MCP client" });
      setFresh({ token: r.token, name: r.record.name });
      setCreating(false);
      void tokens.reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (t: McpToken) => {
    if (!window.confirm(`Revoke "${t.name}"? Clients using it stop working immediately.`)) return;
    try { await api.del(`/mcp/tokens/${t.id}`); toast("Token revoked."); void tokens.reload(); if (fresh && t.prefix === fresh.token.slice(0, 11)) setFresh(null); } catch (e) { toast(e instanceof Error ? e.message : String(e), "err"); }
  };

  const clients = activity.data?.clients ?? [];
  const external = clients.filter((c) => !["web", "assistant", "seed"].includes(c.client));

  return (
    <>
      <PageHead title="Connect" sub="Use your ledger from the AI assistants you already have. They call the same MCP tools this app does." />
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="flow">
          <div className="node">Web app<small>this screen, client "web"</small></div>
          <div className="arrow"><Icon name="arrowRight" /></div>
          <div className="node core">FinMCP MCP server<small>{catalog.data ? `${catalog.data.tools.length} tools · ${catalog.data.resources.length} resources · ${catalog.data.prompts.length} prompts` : "tools · resources · prompts"}</small></div>
          <div className="arrow"><Icon name="arrowRight" /></div>
          <div className="node">Postgres<small>row-level security per account</small></div>
        </div>
        <p className="small muted" style={{ marginTop: 14 }}>Claude Desktop, Claude Code, Cursor and the in-app assistant enter the same door. Every write is stamped with the client that made it, and the database only ever shows an account its own rows.</p>
      </section>

      <div className="steps" style={{ marginBottom: 16 }}>
        <div className="step"><div className="n">1</div><h3>Create a token</h3><p>One per client, shown once. Revoke any time.</p></div>
        <div className="step"><div className="n">2</div><h3>Paste one snippet</h3><p>Pick your client below; the config is ready to copy.</p></div>
        <div className="step"><div className="n">3</div><h3>Ask about your money</h3><p>“What did I spend on food?” “Add 450 for Swiggy.” “Which bills are due?”</p></div>
      </div>

      <div className="grid wide-left">
        <section className="card">
          <div className="card-head"><h2>Configuration</h2><span className="meta mono">{endpoint}</span></div>
          <div className="tabs" style={{ marginBottom: 6, flexWrap: "wrap", display: "flex" }}>
            {CLIENTS.map((c) => <button key={c.id} className={client === c.id ? "on" : ""} onClick={() => setClient(c.id)}>{c.label}</button>)}
          </div>
          <div className="codebox">
            <button className="copy" onClick={() => void copy(snippet(client, endpoint, fresh?.token ?? ""))}>Copy</button>
            {snippet(client, endpoint, fresh?.token ?? "")}
          </div>
          <p className="small muted" style={{ marginTop: 10 }}>{NOTES[client]}{!fresh ? " Create a token first and it is filled in for you." : ""}</p>
        </section>

        <section className="card">
          <div className="card-head"><h2>Tokens</h2><button className="btn sm primary" onClick={() => setCreating(true)}><Icon name="key" />New token</button></div>
          {fresh ? (
            <div className="token-reveal" style={{ marginBottom: 12 }}>
              <div className="strong small">{fresh.name}: copy it now, it will not be shown again.</div>
              <code>{fresh.token}</code>
              <button className="btn sm" onClick={() => void copy(fresh.token)}><Icon name="copy" />Copy token</button>
            </div>
          ) : null}
          {tokens.error ? <ErrorBox>{tokens.error}</ErrorBox> : null}
          {!tokens.data ? <div className="stack"><Skeleton /><Skeleton /></div> : !tokens.data.length ? <Empty>No tokens yet.</Empty> : (
            <div className="list">
              {tokens.data.map((t) => (
                <div className="item" key={t.id}>
                  <div className="grow"><div className="t">{t.name} <span className="mono muted micro">{t.prefix}…</span></div><div className="s">{t.last_used_at ? `last used ${relTime(t.last_used_at)}${t.last_client ? ` by ${t.last_client}` : ""}` : "never used"} · created {relTime(t.created_at)}</div></div>
                  <button className="btn ghost sm" onClick={() => void revoke(t)}>Revoke</button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>Connected clients</h2><span className="meta">from the activity trail</span></div>
        {!activity.data ? <Skeleton /> : !external.length ? <Empty>No external client has written to this ledger yet. Once Claude Desktop or Claude Code adds or edits something, it shows up here with its name.</Empty> : (
          <div className="chips">
            {external.map((c) => <span key={c.client} className="chip outline" title={`${c.actions} actions · first seen ${relTime(c.first_seen)}`}><ClientPill name={c.client} /> {c.actions} actions · {relTime(c.last_seen)}</span>)}
          </div>
        )}
        {clients.length ? <div className="chips" style={{ marginTop: 10 }}>{clients.filter((c) => ["web", "assistant", "seed"].includes(c.client)).map((c) => <Chip key={c.client}><ClientPill name={c.client} /> {c.actions}</Chip>)}</div> : null}
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h2>What a client can do</h2><span className="meta">{catalog.data ? `${catalog.data.tools.length} tools` : ""}</span></div>
        {catalog.error ? <ErrorBox>{catalog.error}</ErrorBox> : null}
        {!catalog.data ? <div className="stack"><Skeleton /><Skeleton /></div> : (
          <>
            <div className="tool-grid">
              {catalog.data.tools.map((t) => (
                <div className="tool" key={t.name}>
                  <div className="n">{t.name}{t.destructive ? <Chip tone="bad">destructive</Chip> : t.read_only ? <Chip tone="good">read</Chip> : <Chip tone="accent">write</Chip>}</div>
                  <div className="d">{t.description?.split(/(?<=\.)\s/)[0]}</div>
                </div>
              ))}
            </div>
            <div className="small muted" style={{ marginTop: 14 }}>
              Resources: {catalog.data.resources.map((r) => r.uri).join(", ")}. Prompts: {catalog.data.prompts.map((p) => p.title).join(", ")}.
            </div>
          </>
        )}
      </section>

      <Sheet open={creating} onClose={() => setCreating(false)} title="New token" sub="Name it after the client so you can tell them apart later.">
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <div className="field"><label>Name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} autoFocus /></div>
          <div className="chips">{["Claude Desktop", "Claude Code", "Cursor", "Script"].map((n) => <button type="button" key={n} className={`chip btn-chip ${name === n ? "on" : ""}`} onClick={() => setName(n)}>{n}</button>)}</div>
          <button className="btn primary" type="submit" disabled={busy}>{busy ? <Spinner /> : <><Icon name="key" />Create token</>}</button>
        </form>
      </Sheet>
    </>
  );
}
