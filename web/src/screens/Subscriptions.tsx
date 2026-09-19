import { useState } from "react";
import { Link } from "react-router-dom";
import { Avatar, Chip, Empty, ErrorBox, Icon, PageHead, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { dateLabel, money } from "../lib/format";
import { useStatus } from "../lib/status";
import type { Recurring, RecurringReport } from "../lib/types";
import { useApi } from "../lib/useApi";

function due(u: Recurring): { text: string; tone: "good" | "warn" | "bad" | "" } {
  if (u.status === "overdue") return { text: `expected ${dateLabel(u.next_due)}`, tone: "warn" };
  if (u.days_until === 0) return { text: "due today", tone: "bad" };
  if (u.days_until === 1) return { text: "due tomorrow", tone: "bad" };
  if (u.days_until <= 7) return { text: `in ${u.days_until} days`, tone: "warn" };
  return { text: dateLabel(u.next_due), tone: "" };
}

export default function Subscriptions() {
  const { currency } = useStatus();
  const r = useApi(() => api.get<RecurringReport>("/recurring"), []);
  const [includeTransfers, setIncludeTransfers] = useState(false);
  const items = (r.data?.items ?? []).filter((i) => includeTransfers || i.category_kind !== "transfer");
  const monthly = includeTransfers ? r.data?.monthly_total : r.data?.monthly_expenses;

  return (
    <>
      <PageHead title="Subscriptions & bills" sub="Detected from payment rhythm: anything that repeats weekly, monthly, quarterly or yearly.">
        <Chip onClick={() => setIncludeTransfers((v) => !v)} on={includeTransfers} title="SIPs, card bill payments and other transfers">Include SIPs & transfers</Chip>
      </PageHead>
      {r.error ? <ErrorBox>{r.error}</ErrorBox> : null}
      {r.data ? (
        <section className="card" style={{ marginBottom: 16 }}>
          <div className="label muted small">Every month, roughly</div>
          <div className="num" style={{ fontSize: 38, fontWeight: 800, letterSpacing: "-0.03em" }}>{money(monthly ?? 0, currency)}</div>
          <div className="small muted">{items.length} recurring payment{items.length === 1 ? "" : "s"} · {money((monthly ?? 0) * 12, currency)} a year</div>
        </section>
      ) : <Skeleton h={120} style={{ marginBottom: 16 }} />}
      <section className="card">
        {!r.data ? <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div> : !items.length ? <Empty>Nothing recurring yet. FinMCP needs three regular payments to the same merchant to call it a bill.</Empty> : (
          <div className="list clickable">
            {items.map((u) => {
              const d = due(u);
              return (
                <Link className="item" key={u.key} to={`/app/transactions?merchant=${encodeURIComponent(u.merchant)}&period=last%2090%20days`}>
                  <Avatar name={u.merchant} neutral />
                  <div className="grow">
                    <div className="t">{u.merchant}</div>
                    <div className="s">{u.cadence}{u.amount_varies ? " · amount varies" : ""} · {u.category ?? "uncategorized"} · seen {u.occurrences}×</div>
                  </div>
                  <div className="right">
                    <div className="amt num">{money(u.amount, currency)}</div>
                    <div className="micro"><Chip tone={d.tone}>{d.text}</Chip></div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>
      <div className="small muted" style={{ marginTop: 14, display: "flex", gap: 6, alignItems: "center" }}><Icon name="spark" />Ask the assistant to run a subscription audit for a ranked list of what to cancel first.</div>
    </>
  );
}
