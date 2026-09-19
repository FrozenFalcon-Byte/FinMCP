/* EMIs: every loan paid back in monthly instalments, how far along it is, what is still owed and when it ends.
   The schedule does the maths (services/emis.py); payments themselves live in the ledger under "Loans & EMI". */
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, FormHero, Icon, PageHead, Sheet, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { compact, dateLabel, money, todayIso } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";
import type { Emi, EmiReport } from "../lib/types";
import { useApi } from "../lib/useApi";

const SPRING = { type: "spring", stiffness: 380, damping: 32 } as const;
const longDate = (iso: string) => dateLabel(iso, { month: "short", year: "numeric" });

function addMonths(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(y, m - 1 + n, 1);
  const last = new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
}

export default function Emis() {
  const { currency } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const r = useApi(() => api.get<EmiReport>("/emis"), []);
  const [open, setOpen] = useState<Emi | "new" | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await fn(); setOpen(null); bump(); toast(done); } catch (e) { toast(e instanceof Error ? e.message : String(e), "err"); } finally { setBusy(false); }
  };

  const d = r.data;
  const active = d?.items.filter((i) => !i.closed) ?? [];
  const closed = d?.items.filter((i) => i.closed) ?? [];
  const lastEnd = active.map((i) => i.ends_on).sort().pop();

  return (
    <>
      <PageHead title="EMIs & loans" sub="Monthly instalments, how far along each loan is, and when you are debt-free.">
        <button className="btn primary sm" onClick={() => setOpen("new")}><Icon name="plus" />Add EMI</button>
      </PageHead>
      {r.error ? <ErrorBox>{r.error}</ErrorBox> : null}

      {d ? (
        <section className="card emi-hero">
          <div>
            <div className="k">Every month</div>
            <div className="big num">{money(d.monthly_total, currency)}</div>
            <div className="s">{d.count} active EMI{d.count === 1 ? "" : "s"}{lastEnd ? <> · loan-free by <b>{longDate(lastEnd)}</b></> : null}</div>
          </div>
          <div className="emi-hero-stats">
            <div><span className="k">Still owed</span><b className="num">{money(d.outstanding, currency)}</b></div>
            <div><span className="k">Next due</span><b>{d.next?.next_due ? `${dateLabel(d.next.next_due)} · ${compact(d.next.amount, currency)}` : "—"}</b></div>
          </div>
        </section>
      ) : <Skeleton h={140} style={{ marginBottom: 16 }} />}

      {!d ? <div className="bud-grid">{[0, 1].map((i) => <Skeleton key={i} h={190} />)}</div>
        : !d.items.length ? <section className="card"><Empty>No EMIs yet. Add one to track what is left on a phone, car or home loan.</Empty></section> : (
          <div className="bud-grid">
            <AnimatePresence initial={false}>
              {[...active, ...closed].map((e, i) => <EmiCard key={e.id} e={e} i={i} currency={currency} onOpen={() => setOpen(e)} />)}
            </AnimatePresence>
          </div>
        )}
      <p className="small muted" style={{ marginTop: 14 }}>
        Payments are filed under <Link to="/app/transactions?category=Loans%20%26%20EMI">Loans &amp; EMI</Link>. Ask the assistant which loan to prepay first.
      </p>

      <Sheet open={open !== null} onClose={() => setOpen(null)} title={open === "new" ? "New EMI" : "Edit EMI"} sub="The instalment, the first due date and the number of months. FinMCP works out the rest.">
        {open !== null ? <EmiForm emi={open === "new" ? null : open} busy={busy} currency={currency}
          onSave={(body) => run(() => (open === "new" ? api.post("/emis", body) : api.put(`/emis/${(open as Emi).id}`, body)), open === "new" ? "EMI added." : "EMI updated.")}
          onDelete={open === "new" ? undefined : () => run(() => api.del(`/emis/${(open as Emi).id}`), "EMI deleted.")} /> : null}
      </Sheet>
    </>
  );
}

function EmiCard({ e, i, currency, onOpen }: { e: Emi; i: number; currency: string; onOpen: () => void }) {
  const soon = e.days_until !== null && e.days_until <= 3;
  return (
    <motion.button type="button" className={`emi-card ${e.closed ? "closed" : ""}`} onClick={onOpen} layout
      initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }} whileHover={{ y: -3 }} whileTap={{ scale: 0.99 }}
      transition={{ ...SPRING, delay: Math.min(i, 8) * 0.04 }}>
      <div className="top">
        <div><div className="n">{e.name}</div><div className="l">{e.lender ?? "Loan"}</div></div>
        <span className={`due ${soon ? "soon" : ""}`}>{e.closed ? "Paid off" : e.days_until === 0 ? "Due today" : e.days_until === 1 ? "Due tomorrow" : `Due ${dateLabel(e.next_due ?? e.ends_on)}`}</span>
      </div>
      <div className="fig"><span className="num">{money(e.amount, currency)}</span><span className="of">/ month</span></div>
      <div className="emi-track" aria-label={`${e.paid_count} of ${e.tenure_months} paid`}>
        <motion.i initial={{ width: 0 }} animate={{ width: `${e.progress_pct}%` }} transition={{ ...SPRING, delay: 0.15 + Math.min(i, 8) * 0.04 }} />
      </div>
      <div className="meta">
        <span><b>{e.paid_count}</b> of {e.tenure_months} paid</span>
        <span>{e.closed ? `ended ${longDate(e.ends_on)}` : <><b>{compact(e.outstanding, currency)}</b> left · ends {longDate(e.ends_on)}</>}</span>
      </div>
      {e.interest ? <div className="int">Interest over the loan: {money(e.interest, currency)}</div> : null}
    </motion.button>
  );
}

function EmiForm({ emi, busy, currency, onSave, onDelete }: {
  emi: Emi | null; busy: boolean; currency: string; onSave: (body: Record<string, unknown>) => Promise<void>; onDelete?: () => Promise<void>;
}) {
  const [name, setName] = useState(emi?.name ?? "");
  const [lender, setLender] = useState(emi?.lender ?? "");
  const [amount, setAmount] = useState(emi ? String(emi.amount) : "");
  const [start, setStart] = useState(emi?.start_date ?? todayIso());
  const [tenure, setTenure] = useState(emi ? String(emi.tenure_months) : "12");
  const [principal, setPrincipal] = useState(emi?.principal ? String(emi.principal) : "");
  const a = Number(amount) || 0;
  const n = Math.max(0, Math.round(Number(tenure) || 0));
  const p = Number(principal) || 0;
  const total = a * n;
  const valid = name.trim() && a > 0 && n >= 1 && n <= 480 && !!start;
  return (
    <form className="stack" style={{ gap: 14 }} onSubmit={(ev) => { ev.preventDefault(); if (valid) void onSave({ name: name.trim(), lender: lender.trim() || undefined, amount: a, start_date: start, tenure_months: n, principal: p > 0 ? p : undefined }); }}>
      <FormHero value={`${money(a, currency)} × ${n || 0}`}
        sub={a && n ? <>{money(total, currency)} in all{p && total > p ? <> · <b>{money(total - p, currency)} interest</b></> : null} · last EMI {longDate(addMonths(start, n - 1))}</> : "Enter the instalment and the months"} />
      <div className="form-grid">
        <div className="field full"><label>What is it for</label><input className="input" value={name} onChange={(ev) => setName(ev.target.value)} placeholder="iPhone 16, Car loan" required maxLength={80} autoFocus /></div>
        <div className="field"><label>Monthly EMI ({currency})</label><input className="input num" type="number" min="1" step="any" value={amount} onChange={(ev) => setAmount(ev.target.value)} required /></div>
        <div className="field"><label>Months</label><input className="input num" type="number" min="1" max="480" value={tenure} onChange={(ev) => setTenure(ev.target.value)} required /></div>
        <div className="field"><label>First EMI on</label><input className="input" type="date" value={start} onChange={(ev) => setStart(ev.target.value)} required /></div>
        <div className="field"><label>Lender</label><input className="input" value={lender} onChange={(ev) => setLender(ev.target.value)} placeholder="Bajaj Finserv" maxLength={80} /></div>
        <div className="field full"><label>Amount borrowed (optional)</label><input className="input num" type="number" min="0" step="any" value={principal} onChange={(ev) => setPrincipal(ev.target.value)} placeholder="shows the interest you pay" /></div>
      </div>
      <div className="actions" style={{ marginTop: 6 }}>
        {onDelete ? <button type="button" className="btn danger" onClick={() => void onDelete()} disabled={busy}><Icon name="trash" />Delete</button> : null}
        <button className="btn primary" type="submit" disabled={busy || !valid}>{busy ? <Spinner /> : <><Icon name="check" />{emi ? "Save EMI" : "Add EMI"}</>}</button>
      </div>
    </form>
  );
}
