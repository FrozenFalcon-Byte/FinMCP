import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Bar, Chip, Empty, ErrorBox, Icon, PageHead, Ring, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { compact, money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";
import type { BudgetCategory, BudgetSummary, Summary } from "../lib/types";
import { useApi } from "../lib/useApi";

export default function Budgets() {
  const { currency } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const navigate = useNavigate();
  const [month, setMonth] = useState<string | undefined>(undefined);
  const b = useApi(() => api.get<BudgetSummary>("/budget", month ? { month } : undefined), [month]);
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async (name: string, limit: number | null) => {
    setBusy(true);
    try {
      await api.put(`/categories/${encodeURIComponent(name)}/budget`, { monthly_limit: limit });
      setEditing(null);
      bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  const suggest = async () => {
    setBusy(true);
    try {
      const s = await api.get<Summary>("/summary", { period: "last 3 months", group_by: "category", top: 50 });
      const cats = s.breakdown.filter((c) => c.kind === "expense" && c.spent > 0);
      let applied = 0;
      for (const c of cats) {
        const avg = c.spent / 3;
        const limit = Math.max(500, Math.round((avg * 0.9) / 100) * 100);
        await api.put(`/categories/${encodeURIComponent(c.category ?? "")}/budget`, { monthly_limit: limit });
        applied++;
      }
      toast(`Set ${applied} budgets at 10% below your 3-month average.`);
      bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  const d = b.data;
  const used = d?.totals.used_pct ?? 0;
  const budgeted = d?.categories.filter((c) => c.budget_limit) ?? [];
  const unbudgeted = d?.categories.filter((c) => !c.budget_limit) ?? [];

  return (
    <>
      <PageHead title="Budgets" sub={d ? `${d.label} · day ${d.days_elapsed} of ${d.days_in_month}` : "Loading…"}>
        <div className="tabs">
          <button className={!month ? "on" : ""} onClick={() => setMonth(undefined)}>This month</button>
          <button className={month === "last month" ? "on" : ""} onClick={() => setMonth("last month")}>Last month</button>
        </div>
        <button className="btn sm" onClick={() => void suggest()} disabled={busy} title="Sets each expense category to 10% below its three-month average"><Icon name="wand" />Suggest</button>
      </PageHead>
      {b.error ? <ErrorBox>{b.error}</ErrorBox> : null}
      {d ? (
        <section className="card" style={{ marginBottom: 16 }}>
          <div className="row" style={{ gap: 22, flexWrap: "wrap" }}>
            <Ring pct={used} size={120} stroke={12}><b className="num" style={{ fontSize: 22 }}>{d.totals.used_pct != null ? `${Math.round(used)}%` : "—"}</b><span>used</span></Ring>
            <div className="grow">
              <div className="label muted small">Budgeted spend</div>
              <div className="num" style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.03em" }}>{money(d.totals.spent_in_budgeted, currency)} <span className="muted" style={{ fontSize: 16, fontWeight: 600 }}>of {money(d.totals.budget, currency)}</span></div>
              <div className="small muted" style={{ marginTop: 4 }}>{d.totals.remaining >= 0 ? `${money(d.totals.remaining, currency)} left` : `${money(-d.totals.remaining, currency)} over`}{d.is_current_month ? ` · ${d.days_in_month - d.days_elapsed} days to go` : ""}</div>
              <div className="chips" style={{ marginTop: 10 }}>
                <Chip tone="good">{budgeted.filter((c) => c.status === "on_track").length} on track</Chip>
                <Chip tone="warn">{budgeted.filter((c) => c.status === "warning").length} close</Chip>
                <Chip tone="bad">{budgeted.filter((c) => c.status === "exceeded").length} over</Chip>
              </div>
            </div>
          </div>
        </section>
      ) : <Skeleton h={160} style={{ marginBottom: 16 }} />}

      <section className="card">
        <div className="card-head"><h2>By category</h2><span className="meta">tap a limit to change it</span></div>
        {!d ? <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div> : !budgeted.length ? <Empty>No budgets yet. Use Suggest, or set a limit on a category below.</Empty> : null}
        {budgeted.map((c) => <Row key={c.category} c={c} currency={currency} editing={editing} value={value} busy={busy} onEdit={(n) => { setEditing(n); setValue(String(c.budget_limit ?? "")); }} onValue={setValue} onSave={save} onCancel={() => setEditing(null)} onOpen={() => navigate(`/app/transactions?category=${encodeURIComponent(c.category)}&period=${month ? "last%20month" : "this%20month"}`)} isCurrent={!!d?.is_current_month} />)}
        {unbudgeted.length ? (
          <>
            <div className="eyebrow" style={{ margin: "18px 0 6px" }}>No budget</div>
            {unbudgeted.map((c) => <Row key={c.category} c={c} currency={currency} editing={editing} value={value} busy={busy} onEdit={(n) => { setEditing(n); setValue(""); }} onValue={setValue} onSave={save} onCancel={() => setEditing(null)} onOpen={() => navigate(`/app/transactions?category=${encodeURIComponent(c.category)}`)} isCurrent={!!d?.is_current_month} />)}
          </>
        ) : null}
      </section>
    </>
  );
}

function Row({ c, currency, editing, value, busy, onEdit, onValue, onSave, onCancel, onOpen, isCurrent }: {
  c: BudgetCategory; currency: string; editing: string | null; value: string; busy: boolean; isCurrent: boolean;
  onEdit: (name: string) => void; onValue: (v: string) => void; onSave: (name: string, limit: number | null) => Promise<void>; onCancel: () => void; onOpen: () => void;
}) {
  const pct = c.budget_limit ? (c.spent / c.budget_limit) * 100 : 0;
  const isEditing = editing === c.category;
  return (
    <div className="bud-row">
      <div className="n" role="button" tabIndex={0} onClick={onOpen} style={{ cursor: "pointer" }}>{c.category}{c.status === "exceeded" ? <span className="chip bad" style={{ marginLeft: 8, height: 20, fontSize: 11, padding: "0 7px" }}>over</span> : c.status === "warning" ? <span className="chip warn" style={{ marginLeft: 8, height: 20, fontSize: 11, padding: "0 7px" }}>close</span> : null}</div>
      <div className="v num">
        {isEditing ? (
          <form className="row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); void onSave(c.category, value ? Number(value) : null); }}>
            <input className="input num" style={{ height: 34, width: 120, padding: "0 10px" }} type="number" min="0" step="any" value={value} onChange={(e) => onValue(e.target.value)} autoFocus placeholder="no limit" />
            <button className="btn sm primary" type="submit" disabled={busy}>{busy ? <Spinner /> : "Save"}</button>
            <button className="btn sm ghost" type="button" onClick={onCancel}>Cancel</button>
          </form>
        ) : (
          <button className="btn ghost sm" style={{ padding: "0 8px", height: 28, color: "var(--ink-3)" }} onClick={() => onEdit(c.category)}>
            {money(c.spent, currency)}{c.budget_limit ? <> of {compact(c.budget_limit, currency)}</> : <> · set limit</>} <Icon name="edit" />
          </button>
        )}
      </div>
      {c.budget_limit ? <Bar pct={pct} /> : null}
      {c.budget_limit && isCurrent && c.projected_pct != null ? <div className="micro muted" style={{ gridColumn: "1 / -1" }}>on pace for {money(c.projected, currency)} · {Math.round(c.projected_pct)}% of limit</div> : null}
    </div>
  );
}
