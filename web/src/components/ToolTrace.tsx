import type { ToolTraceItem } from "../lib/types";

export function ToolTrace({ items }: { items: ToolTraceItem[] }) {
  if (!items.length) return null;
  return (
    <div className="trace">
      {items.map((t) => {
        const state = t.ok === undefined ? "run" : t.ok ? "ok" : "err";
        return (
          <details key={t.id}>
            <summary>
              <span className={`dot ${state}`} />
              <span className="fn">{t.name}</span>
              <span className="muted">{summarize(t.input)}</span>
              <span className={`st ${state === "err" ? "err" : ""}`}>{t.ok === undefined ? "running" : `${t.ok ? "ok" : "error"} · ${t.elapsed_ms ?? 0} ms`}</span>
            </summary>
            <pre className="pre">{JSON.stringify(t.input, null, 2)}</pre>
            {t.preview !== undefined ? <pre className="pre">{t.preview}</pre> : null}
          </details>
        );
      })}
    </div>
  );
}

function summarize(input: Record<string, unknown>): string {
  const parts = Object.entries(input).slice(0, 3).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`);
  const s = parts.join(", ");
  return s.length > 70 ? s.slice(0, 68) + "…" : s;
}
