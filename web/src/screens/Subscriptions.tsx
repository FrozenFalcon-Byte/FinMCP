/* Subscriptions & bills.

   The list is read out of history — nobody declares a subscription here, the payment rhythm does. What you *can*
   say about one is "stop making me type this": autopay files each cycle on its due date, from the same detected
   amount, with the fingerprint the bank's own copy would carry so the statement import recognises it rather than
   filing it twice.

   The second half of the question is how much these things have actually taken, so every row carries its own
   record: how many times it has been paid, what that came to this year, and what autopay itself has filed. */
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Avatar, Chip, Empty, ErrorBox, Icon, PageHead, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { dateLabel, money } from "../lib/format";
import { useStatus } from "../lib/status";
import type { Recurring, RecurringReport } from "../lib/types";
import { useApi } from "../lib/useApi";

const SPRING = { type: "spring", stiffness: 420, damping: 34 } as const;

function due(u: Recurring): { text: string; tone: "good" | "warn" | "bad" | "" } {
  if (u.status === "overdue") return { text: `expected ${dateLabel(u.next_due)}`, tone: "warn" };
  if (u.days_until === 0) return { text: "due today", tone: "bad" };
  if (u.days_until === 1) return { text: "due tomorrow", tone: "bad" };
  if (u.days_until <= 7) return { text: `in ${u.days_until} days`, tone: "warn" };
  return { text: dateLabel(u.next_due), tone: "" };
}

/** The switch. It is the one thing on this page that changes anything, so it says which way it is and what that
    means, rather than being a bare toggle you have to test to understand. */
function AutoSwitch({ on, busy, onChange }: { on: boolean; busy: boolean; onChange: (next: boolean) => void }) {
  return (
    <button type="button" className={`autosw ${on ? "on" : ""}`} disabled={busy} aria-pressed={on}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); onChange(!on); }}
      title={on ? "Autopay is on: each cycle is filed on its due date" : "File this bill automatically on its due date"}>
      <motion.span className="knob" layout transition={SPRING}>{busy ? <span className="spinner tiny" /> : on ? <Icon name="bolt" /> : null}</motion.span>
      <span className="lbl">{on ? "Auto" : "Off"}</span>
    </button>
  );
}

export default function Subscriptions() {
  const { currency } = useStatus();
  const toast = useToast();
  const r = useApi(() => api.get<RecurringReport>("/recurring"), []);
  const [includeTransfers, setIncludeTransfers] = useState(false);
  const [only, setOnly] = useState<"all" | "auto" | "soon">("all");
  const [pending, setPending] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const all = useMemo(() => (r.data?.items ?? []).filter((i) => includeTransfers || i.category_kind !== "transfer"), [r.data, includeTransfers]);
  const items = useMemo(() => {
    if (only === "auto") return all.filter((i) => i.autopay?.active);
    if (only === "soon") return all.filter((i) => i.days_until <= 14);
    return all;
  }, [all, only]);

  const monthly = includeTransfers ? r.data?.monthly_total : r.data?.monthly_expenses;
  const autoCount = all.filter((i) => i.autopay?.active).length;
  const filed = all.reduce((n, i) => n + (i.autopay?.posted_count ?? 0), 0);
  const paid12 = all.reduce((n, i) => n + i.paid_12m, 0);

  const toggle = async (u: Recurring, next: boolean) => {
    setPending(u.key);
    try {
      await api.post("/recurring/autopay", { merchant: u.merchant, active: next });
      const back = await api.post<{ posted_count: number }>("/recurring/autopay/run", {});
      await r.reload();
      if (next) toast(back.posted_count ? `Autopay on · filed ${back.posted_count} due ${back.posted_count === 1 ? "entry" : "entries"}` : `Autopay on for ${u.merchant}`, "ok");
      else toast(`Autopay off for ${u.merchant}`, "ok");
      window.dispatchEvent(new Event("finmcp:ledger-changed"));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setPending(null);
    }
  };

  return (
    <>
      <PageHead title="Subscriptions & bills" sub="Found in your own history: anything that repeats weekly, monthly, quarterly or yearly.">
        <Chip onClick={() => setIncludeTransfers((v) => !v)} on={includeTransfers} title="SIPs, card bill payments and other transfers">Include SIPs & transfers</Chip>
      </PageHead>
      {r.error ? <ErrorBox>{r.error}</ErrorBox> : null}

      {r.data ? (
        <section className="sub-tiles">
          <motion.div className="card sub-tile lead" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
            <div className="label muted small">Every month, roughly</div>
            <div className="num big">{money(monthly ?? 0, currency)}</div>
            <div className="small muted">{all.length} recurring payment{all.length === 1 ? "" : "s"} · {money((monthly ?? 0) * 12, currency)} a year</div>
          </motion.div>
          <motion.div className="card sub-tile" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.05 }}>
            <div className="label muted small">Paid in the last year</div>
            <div className="num mid">{money(paid12, currency)}</div>
            <div className="small muted">across {all.reduce((n, i) => n + i.occurrences, 0)} payments</div>
          </motion.div>
          <motion.div className="card sub-tile" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.1 }}>
            <div className="label muted small">On autopay</div>
            <div className="num mid">{autoCount}<span className="of"> of {all.length}</span></div>
            <div className="small muted">{filed ? `${filed} ${filed === 1 ? "entry" : "entries"} filed for you` : "nothing filed yet"}</div>
          </motion.div>
        </section>
      ) : <Skeleton h={130} style={{ marginBottom: 16 }} />}

      <div className="sub-filter">
        {([["all", "Everything"], ["soon", "Due soon"], ["auto", "On autopay"]] as const).map(([k, label]) => (
          <button key={k} type="button" className={only === k ? "on" : ""} onClick={() => setOnly(k)}>
            {only === k ? <motion.span layoutId="sub-filter-pill" className="pill" transition={SPRING} /> : null}
            <span>{label}</span>
          </button>
        ))}
      </div>

      <section className="card">
        {!r.data ? <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div> : !items.length ? (
          <Empty>{only === "auto" ? "Nothing on autopay yet. Turn it on for a bill and its entries file themselves on the day." : only === "soon" ? "Nothing due in the next fortnight." : "Nothing recurring yet. FinMCP needs three regular payments to the same merchant to call it a bill."}</Empty>
        ) : (
          <div className="list sub-list">
            {items.map((u) => {
              const d = due(u);
              const auto = !!u.autopay?.active;
              const shown = open === u.key;
              return (
                <div className={`sub-row ${auto ? "auto" : ""}`} key={u.key}>
                  <button type="button" className="item head" onClick={() => setOpen(shown ? null : u.key)} aria-expanded={shown}>
                    <Avatar name={u.merchant} neutral />
                    <div className="grow">
                      <div className="t">{u.merchant}{auto ? <span className="tag"><Icon name="bolt" />autopay</span> : null}</div>
                      <div className="s">{u.cadence}{u.amount_varies ? " · amount varies" : ""} · {u.category ?? "uncategorized"} · paid {u.occurrences}×</div>
                    </div>
                    <div className="right">
                      <div className="amt num">{money(u.amount, currency)}</div>
                      <div className="micro"><Chip tone={d.tone}>{d.text}</Chip></div>
                    </div>
                    <AutoSwitch on={auto} busy={pending === u.key} onChange={(next) => void toggle(u, next)} />
                  </button>

                  <AnimatePresence initial={false}>
                    {shown ? (
                      <motion.div className="sub-more" key="more" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}>
                        <div className="sub-facts">
                          <div><span>Paid</span><b>{u.occurrences}×</b></div>
                          <div><span>This year</span><b>{u.count_this_year}× · {money(u.paid_this_year, currency)}</b></div>
                          <div><span>Last 12 months</span><b>{money(u.paid_12m, currency)}</b></div>
                          <div><span>Since {dateLabel(u.first_date)}</span><b>{money(u.paid_total, currency)}</b></div>
                          <div><span>Last paid</span><b>{dateLabel(u.last_date)} · {money(u.last_amount, currency)}</b></div>
                          {u.autopay ? <div><span>Autopay filed</span><b>{u.autopay.posted_count}× {u.autopay.last_posted_on ? `· last ${dateLabel(u.autopay.last_posted_on)}` : ""}</b></div> : null}
                        </div>
                        <div className="sub-acts">
                          <Link className="btn sm" to={`/app/transactions?merchant=${encodeURIComponent(u.merchant)}&period=last%20365%20days`}>
                            <Icon name="list" />See every payment
                          </Link>
                          {auto ? <span className="small muted">Next one files itself on {dateLabel(u.autopay!.next_due)}.</span>
                                : <span className="small muted">Autopay would file {money(u.amount, currency)} on {dateLabel(u.next_due)}.</span>}
                        </div>
                      </motion.div>
                    ) : null}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className="small muted sub-note">
        <Icon name="spark" />
        Autopay only files a cycle whose date has passed, and gives it the same fingerprint your bank statement would — so importing the statement later recognises the payment instead of filing it twice.
      </div>
    </>
  );
}
