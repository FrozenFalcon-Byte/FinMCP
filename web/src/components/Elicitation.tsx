/* The client half of MCP elicitation. When the server needs a decision (where to file an unclear transaction,
   whether to really delete one) it sends `elicitation/create`; the API parks the request and this dialog answers it.
   The form is built from the JSON schema the server sent, so any tool can ask anything flat. */
import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useFeed, type JsonSchema, type Question } from "../lib/mcp";
import { Icon } from "./ui";

type Value = string | number | boolean | undefined;

function initial(schema: JsonSchema): Record<string, Value> {
  const out: Record<string, Value> = {};
  for (const [k, p] of Object.entries(schema.properties ?? {})) out[k] = (p.default as Value) ?? (p.type === "boolean" ? false : undefined);
  return out;
}

function Field({ name, prop, value, onChange }: { name: string; prop: JsonSchema; value: Value; onChange: (v: Value) => void }) {
  const label = prop.title ?? name.replace(/_/g, " ");
  if (prop.enum) {
    return (
      <div className="elicit-field">
        <div className="elicit-label">{prop.description ?? label}</div>
        <div className="elicit-options">
          {prop.enum.map((o) => (
            <button key={String(o)} type="button" className={`elicit-opt ${value === o ? "on" : ""} ${o === "skip" ? "skip" : ""}`} onClick={() => onChange(o)}>
              {o === "skip" ? "Leave it for now" : String(o)}
            </button>
          ))}
        </div>
      </div>
    );
  }
  if (prop.type === "boolean") {
    return (
      <label className="elicit-check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>{prop.description ?? label}</span>
      </label>
    );
  }
  const numeric = prop.type === "number" || prop.type === "integer";
  return (
    <label className="field">
      <span>{prop.description ?? label}</span>
      <input className="input" type={numeric ? "number" : "text"} value={value === undefined ? "" : String(value)}
        onChange={(e) => onChange(numeric ? (e.target.value === "" ? undefined : Number(e.target.value)) : e.target.value)} />
    </label>
  );
}

export function ElicitationHost() {
  const [queue, setQueue] = useState<Question[]>([]);
  const [values, setValues] = useState<Record<string, Value>>({});
  const [busy, setBusy] = useState(false);
  const current = queue[0];

  const load = useCallback(() => {
    api.get<{ questions: Question[] }>("/mcp/elicitations").then((r) => setQueue(r.questions)).catch(() => {});
  }, []);
  useEffect(load, [load]);
  useFeed((ev) => {
    if (ev.type === "elicit" && ev.id && ev.schema) {
      const q = ev as unknown as Question;
      setQueue((qs) => (qs.some((x) => x.id === q.id) ? qs : [...qs, q]));
    } else if (ev.type === "elicit_done") {
      setQueue((qs) => qs.filter((x) => x.id !== ev.id));
    } else if (ev.type === "hello") load();
  });
  useEffect(() => { if (current) setValues(initial(current.schema)); }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!current) return null;
  const answer = async (action: "accept" | "decline" | "cancel") => {
    setBusy(true);
    try {
      await api.post(`/mcp/elicitations/${current.id}`, { action, content: action === "accept" ? values : null });
    } catch { /* already answered or timed out */ }
    setQueue((qs) => qs.filter((x) => x.id !== current.id));
    setBusy(false);
  };
  const props = current.schema.properties ?? {};
  const missing = (current.schema.required ?? []).some((k) => values[k] === undefined || values[k] === "");
  return (
    <div className="elicit-backdrop" role="dialog" aria-modal="true" aria-labelledby="elicit-title">
      <div className="elicit">
        <div className="elicit-head">
          <span className="elicit-badge"><Icon name="spark" /> elicitation/create</span>
          <span className="micro muted">from FinMCP · via {current.client === "assistant" ? "the assistant" : "this app"}</span>
        </div>
        <h3 id="elicit-title">{current.message}</h3>
        <div className="elicit-body">
          {Object.entries(props).map(([k, p]) => <Field key={k} name={k} prop={p} value={values[k]} onChange={(v) => setValues((s) => ({ ...s, [k]: v }))} />)}
        </div>
        <div className="elicit-actions">
          <button className="btn ghost" disabled={busy} onClick={() => answer("decline")}>Decline</button>
          <button className="btn primary" disabled={busy || missing} onClick={() => answer("accept")}>Send answer</button>
        </div>
        <p className="micro muted">The server paused the tool call and is waiting for this answer. It gives up after 90 seconds.</p>
      </div>
    </div>
  );
}
