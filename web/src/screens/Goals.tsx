import { useState } from "react";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Icon, PageHead, Ring, Sheet, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { compact, dateLabel, money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";
import type { Goal } from "../lib/types";
import { useApi } from "../lib/useApi";

const ICONS = ["🎯", "🛟", "✈️", "🏠", "🚲", "💻", "🎓", "💍", "🐶", "🌱"];

export default function Goals() {
  const { currency } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const g = useApi(() => api.get<{ goals: Goal[] }>("/goals"), []);
  const [open, setOpen] = useState<Goal | "new" | null>(null);
  const [adding, setAdding] = useState<Goal | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try { await fn(); setOpen(null); setAdding(null); bump(); if (done) toast(done); } catch (e) { toast(e instanceof Error ? e.message : String(e), "err"); } finally { setBusy(false); }
  };

  const goals = g.data?.goals ?? [];
  const totalSaved = goals.reduce((s, x) => s + x.saved, 0);
  const totalTarget = goals.reduce((s, x) => s + x.target, 0);

  return (
    <>
      <PageHead title="Goals" sub={goals.length ? `${money(totalSaved, currency)} saved of ${money(totalTarget, currency)}` : "Save towards something with a monthly number."}>
        <button className="btn primary sm" onClick={() => setOpen("new")}><Icon name="plus" />New goal</button>
      </PageHead>
      {g.error ? <ErrorBox>{g.error}</ErrorBox> : null}
      {g.loading && !g.data ? <div className="grid two"><Skeleton h={120} /><Skeleton h={120} /></div> : null}
      {g.data && !goals.length ? <Empty>No goals yet. Create one and FinMCP works out the monthly amount.</Empty> : null}
      <div className="grid two">
        {goals.map((x) => (
          <section className="card" key={x.id}>
            <div className="goal-card">
              <Ring pct={x.progress_pct ?? 0} size={92} stroke={10}><b className="num">{Math.round(x.progress_pct ?? 0)}%</b><span>saved</span></Ring>
              <div className="grow">
                <div className="between"><h2 className="ellipsis">{x.icon ? `${x.icon} ` : ""}{x.name}</h2><button className="btn ghost icon sm" aria-label="Edit" onClick={() => setOpen(x)}><Icon name="edit" /></button></div>
                <div className="num" style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>{money(x.saved, currency)} <span className="muted" style={{ fontSize: 14, fontWeight: 600 }}>of {compact(x.target, currency)}</span></div>
                <div className="small muted">
                  {x.saved >= x.target ? "Reached. Nice." : x.monthly_needed ? `${money(x.monthly_needed, currency)} a month until ${x.due ? dateLabel(x.due, { day: "numeric", month: "short", year: "numeric" }) : ""}` : `${money(x.remaining ?? x.target - x.saved, currency)} to go`}
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <button className="btn sm soft" onClick={() => setAdding(x)}><Icon name="plus" />Add money</button>
                </div>
              </div>
            </div>
          </section>
        ))}
      </div>

      <Sheet open={open !== null} onClose={() => setOpen(null)} title={open === "new" ? "New goal" : "Edit goal"} sub="A target, an optional date, and FinMCP tells you the monthly amount.">
        {open !== null ? <GoalForm goal={open === "new" ? null : open} busy={busy} currency={currency}
          onSave={(body) => run(() => (open === "new" ? api.post("/goals", body) : api.patch(`/goals/${(open as Goal).id}`, body)), open === "new" ? "Goal created." : "Goal updated.")}
          onDelete={open === "new" ? undefined : () => run(() => api.del(`/goals/${(open as Goal).id}`), "Goal deleted.")} /> : null}
      </Sheet>

      <Sheet open={!!adding} onClose={() => setAdding(null)} title={adding ? `Add to ${adding.name}` : ""} sub="Moves money into the goal balance. Use a negative amount to take some out.">
        {adding ? <AddForm busy={busy} currency={currency} onSave={(amount) => run(() => api.post(`/goals/${adding.id}/add`, { amount }), `Added ${money(amount, currency)}.`)} /> : null}
      </Sheet>
    </>
  );
}

function GoalForm({ goal, busy, currency, onSave, onDelete }: { goal: Goal | null; busy: boolean; currency: string; onSave: (body: Record<string, unknown>) => Promise<void>; onDelete?: () => Promise<void> }) {
  const [name, setName] = useState(goal?.name ?? "");
  const [target, setTarget] = useState(goal ? String(goal.target) : "");
  const [saved, setSaved] = useState(goal ? String(goal.saved) : "0");
  const [due, setDue] = useState(goal?.due ?? "");
  const [icon, setIcon] = useState(goal?.icon ?? "🎯");
  return (
    <form className="stack" style={{ gap: 14 }} onSubmit={(e) => { e.preventDefault(); void onSave({ name: name.trim(), target: Number(target), saved: Number(saved) || 0, due: due || undefined, icon }); }}>
      <div className="chips">{ICONS.map((i) => <button type="button" key={i} className={`chip btn-chip ${icon === i ? "on" : ""}`} onClick={() => setIcon(i)} style={{ fontSize: 16 }}>{i}</button>)}</div>
      <div className="form-grid">
        <div className="field full"><label>Name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Emergency fund" required maxLength={80} autoFocus /></div>
        <div className="field"><label>Target ({currency})</label><input className="input num" type="number" min="1" step="any" value={target} onChange={(e) => setTarget(e.target.value)} required /></div>
        <div className="field"><label>Saved so far</label><input className="input num" type="number" min="0" step="any" value={saved} onChange={(e) => setSaved(e.target.value)} /></div>
        <div className="field full"><label>Deadline</label><input className="input" type="date" value={due} onChange={(e) => setDue(e.target.value)} /><span className="help">Optional. With a date, the monthly amount appears.</span></div>
      </div>
      <div className="actions" style={{ marginTop: 6 }}>
        {onDelete ? <button type="button" className="btn danger" onClick={() => void onDelete()} disabled={busy}><Icon name="trash" />Delete</button> : null}
        <button className="btn primary" type="submit" disabled={busy || !name.trim() || Number(target) <= 0}>{busy ? <Spinner /> : <><Icon name="check" />Save goal</>}</button>
      </div>
    </form>
  );
}

function AddForm({ busy, currency, onSave }: { busy: boolean; currency: string; onSave: (amount: number) => Promise<void> }) {
  const [amount, setAmount] = useState("");
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); if (Number(amount)) void onSave(Number(amount)); }}>
      <div className="field"><label>Amount ({currency})</label><input className="input num" type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus required /></div>
      <div className="chips">{[1000, 5000, 10000, 25000].map((v) => <button key={v} type="button" className="chip btn-chip" onClick={() => setAmount(String(v))}>+{compact(v, currency)}</button>)}</div>
      <button className="btn primary" type="submit" disabled={busy || !Number(amount)}>{busy ? <Spinner /> : "Add"}</button>
    </form>
  );
}
