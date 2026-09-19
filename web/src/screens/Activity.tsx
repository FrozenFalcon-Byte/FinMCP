import { useState } from "react";
import { Chip, ClientPill, Empty, ErrorBox, Icon, PageHead, Skeleton, Spinner, clientLabel } from "../components/ui";
import { api } from "../lib/api";
import { money, relTime } from "../lib/format";
import { useStatus } from "../lib/status";
import type { Activity as ActivityData, ActivityItem } from "../lib/types";
import { useApi } from "../lib/useApi";

const VERBS: Record<string, string> = {
  insert: "added", update: "edited", delete: "deleted", categorize: "categorised", user_categorize: "filed", import: "imported", seed_demo_data: "seeded sample data", budget: "set a budget",
};

function describe(it: ActivityItem, currency: string): string {
  const d = it.detail ?? {};
  const verb = VERBS[it.action] ?? it.action.replace(/_/g, " ");
  if (it.entity === "transaction") {
    const who = (d.merchant as string | undefined) ?? `transaction #${it.entity_id ?? "?"}`;
    const amt = typeof d.amount === "number" ? ` · ${money(d.amount, currency)}` : "";
    const cat = typeof d.category === "string" && d.category ? ` → ${d.category}` : "";
    return `${verb} ${who}${amt}${cat}`;
  }
  if (it.entity === "category") return `${verb} for ${(d.category as string | undefined) ?? "a category"}${typeof d.budget_limit === "number" ? ` · ${money(d.budget_limit, currency)}` : ""}`;
  if (it.entity === "goal") return `${verb} goal${d.name ? ` ${d.name}` : ` #${it.entity_id}`}${typeof d.amount === "number" ? ` · ${money(d.amount, currency)}` : ""}`;
  if (it.entity === "import") return `imported ${d.inserted ?? 0} new (${d.duplicates ?? 0} duplicates) from ${(d.source as string | undefined) ?? "a file"}`;
  return verb;
}

export default function Activity() {
  const { currency } = useStatus();
  const [client, setClient] = useState<string | null>(null);
  const [limit, setLimit] = useState(40);
  const a = useApi(() => api.get<ActivityData>("/activity", { limit }), [limit]);
  const items = (a.data?.items ?? []).filter((i) => !client || (i.client ?? "unknown") === client);

  return (
    <>
      <PageHead title="Activity" sub="Everything that changed your ledger, and which client did it. This is the MCP audit trail." />
      {a.error ? <ErrorBox>{a.error}</ErrorBox> : null}
      {a.data?.clients.length ? (
        <div className="chips" style={{ marginBottom: 16 }}>
          <Chip onClick={() => setClient(null)} on={client === null}>All clients</Chip>
          {a.data.clients.map((c) => <Chip key={c.client} onClick={() => setClient(client === c.client ? null : c.client)} on={client === c.client}>{clientLabel(c.client)} · {c.actions}</Chip>)}
        </div>
      ) : null}
      <section className="card">
        {!a.data ? <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div> : !items.length ? <Empty>Nothing yet.</Empty> : items.map((it) => (
          <div className="act" key={it.id}>
            <ClientPill name={it.client} />
            <div className="grow"><div className="what">{describe(it, currency)}</div>{it.detail?.reasoning ? <div className="det">{String(it.detail.reasoning)}</div> : it.detail?.source && it.entity === "transaction" && it.action === "categorize" ? <div className="det">by {String(it.detail.source)}</div> : null}</div>
            <div className="when" title={it.ts}>{relTime(it.ts)}</div>
          </div>
        ))}
        {a.data && a.data.items.length >= limit ? <div style={{ textAlign: "center", marginTop: 12 }}><button className="btn sm" onClick={() => setLimit((l) => l + 60)} disabled={a.loading}>{a.loading ? <Spinner /> : <><Icon name="arrowDown" />More</>}</button></div> : null}
      </section>
    </>
  );
}
