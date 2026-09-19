/* Budgets: how much is left this month, and each category as a card you can read at a glance. The bar shows what is
   spent, a faint extension shows where the current pace ends the month, and a tick marks where you "should" be by
   today. Tap a card to see its transactions; the pencil opens a slider to change the limit, with a live preview. */
import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Icon, PageHead, Ring, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { compact, money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { useStatus } from "../lib/status";
import type { BudgetCategory, BudgetSummary, Category, Summary } from "../lib/types";
import { useApi } from "../lib/useApi";

type Filter = "all" | "exceeded" | "warning" | "on_track";
const FILTERS: { k: Filter; label: string }[] = [{ k: "all", label: "All" }, { k: "exceeded", label: "Over" }, { k: "warning", label: "Close" }, { k: "on_track", label: "On track" }];
const RANK: Record<string, number> = { exceeded: 0, warning: 1, on_track: 2, no_budget: 3 };
const SPRING = { type: "spring", stiffness: 380, damping: 32 } as const;

function statusOf(spent: number, limit: number, projected: number): BudgetCategory["status"] {
  if (spent > limit) return "exceeded";
  return projected > limit || spent / limit >= 0.85 ? "warning" : "on_track";
}

export default function Budgets() {
  const { currency } = useStatus();
  const { bump } = useLedger();
  const toast = useToast();
  const navigate = useNavigate();
  const [month, setMonth] = useState<string | undefined>(undefined);
  const b = useApi(() => api.get<BudgetSummary>("/budget", month ? { month } : undefined), [month]);
  const [filter, setFilter] = useState<Filter>("all");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async (name: string, limit: number | null) => {
    setBusy(true);
    try {
      await api.put(`/categories/${encodeURIComponent(name)}/budget`, { monthly_limit: limit });
      setEditing(null);
      bump();
      toast(limit ? `${name}: limit set to ${money(limit, currency)}.` : `${name}: limit removed.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  const suggest = async () => {
    setBusy(true);
    try {
      const [s, all] = await Promise.all([
        api.get<Summary>("/summary", { period: "last 3 months", group_by: "category", top: 50 }), api.get<Category[]>("/categories")]);
      // Only real expense categories: the summary also groups untagged spend as "Uncategorized", which has no budget.
      const known = new Set(all.filter((c) => c.kind === "expense").map((c) => c.name));
      const cats = s.breakdown.filter((c) => c.kind === "expense" && c.spent > 0 && c.category && known.has(c.category));
      const done = await Promise.allSettled(cats.map((c) => api.put(`/categories/${encodeURIComponent(c.category ?? "")}/budget`,
        { monthly_limit: Math.max(500, Math.round((c.spent / 3) * 0.9 / 100) * 100) })));
      const ok = done.filter((r) => r.status === "fulfilled").length;
      toast(ok ? `Set ${ok} budgets at 10% below your 3-month average.` : "No spending in the last 3 months to base budgets on.");
      bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  const d = b.data;
  const budgeted = useMemo(() => (d?.categories.filter((c) => c.budget_limit) ?? [])
    .sort((x, y) => RANK[x.status] - RANK[y.status] || (y.spent / (y.budget_limit ?? 1)) - (x.spent / (x.budget_limit ?? 1))), [d]);
  const unbudgeted = d?.categories.filter((c) => !c.budget_limit && c.spent > 0) ?? [];
  const count = (k: Filter) => (k === "all" ? budgeted.length : budgeted.filter((c) => c.status === k).length);
  const shown = filter === "all" ? budgeted : budgeted.filter((c) => c.status === filter);
  const daysLeft = d ? d.days_in_month - d.days_elapsed : 0;
  const left = d?.totals.remaining ?? 0;
  const today = d?.is_current_month ? d.days_elapsed / d.days_in_month : null;

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
        <section className="card bud-hero">
          <Ring pct={d.totals.used_pct ?? 0} size={132} stroke={7} tone={left < 0 ? "bad" : (d.totals.used_pct ?? 0) > 85 ? "warn" : ""}>
            <b className="num" style={{ fontSize: 24 }}>{d.totals.used_pct != null ? `${Math.round(d.totals.used_pct)}%` : "—"}</b><span>used</span>
          </Ring>
          <div className="grow">
            <div className="k">{left >= 0 ? "Left to spend" : "Over budget by"}</div>
            <div className={`big num ${left < 0 ? "bad" : ""}`}>{money(Math.abs(left), currency)}</div>
            <div className="s">
              {money(d.totals.spent_in_budgeted, currency)} spent of {money(d.totals.budget, currency)}
              {d.is_current_month && left > 0 && daysLeft > 0 ? <> · about <b>{money(left / (daysLeft + 1), currency)} a day</b> for {daysLeft} more days</> : null}
            </div>
          </div>
          <LayoutGroup id="bud-filter">
            <div className="bud-filter" role="tablist">
              {FILTERS.map((f) => (
                <button key={f.k} role="tab" aria-selected={filter === f.k} className={`f-${f.k} ${filter === f.k ? "on" : ""}`} onClick={() => setFilter(f.k)}>
                  {filter === f.k ? <motion.span layoutId="bud-filter-pill" className="pill" transition={SPRING} /> : null}
                  <span className="l">{f.label}</span><span className="c">{count(f.k)}</span>
                </button>
              ))}
            </div>
          </LayoutGroup>
        </section>
      ) : <Skeleton h={170} style={{ marginBottom: 16 }} />}

      {!d ? <div className="bud-grid">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={150} />)}</div>
        : !budgeted.length ? <section className="card"><Empty>No budgets yet. Use Suggest, or set a limit on a category below.</Empty></section> : (
          <motion.div className="bud-grid" layout>
            <AnimatePresence mode="popLayout" initial={false}>
              {shown.map((c, i) => (
                <BudgetCard key={c.category} c={c} i={i} currency={currency} today={today} busy={busy} editing={editing === c.category}
                  onEdit={() => setEditing(editing === c.category ? null : c.category)} onSave={save}
                  onOpen={() => navigate(`/app/transactions?category=${encodeURIComponent(c.category)}&period=${month ? "last%20month" : "this%20month"}`)} />
              ))}
            </AnimatePresence>
          </motion.div>
        )}

      {unbudgeted.length ? (
        <section className="card" style={{ marginTop: 16 }}>
          <div className="card-head"><h2>No limit yet</h2><span className="meta">spent this month</span></div>
          <div className="bud-free">
            {unbudgeted.map((c) => (
              <motion.button key={c.category} className="bud-chip" whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}
                onClick={() => void save(c.category, Math.max(500, Math.ceil((c.spent * 1.1) / 500) * 500))} disabled={busy}
                title={`Set a limit of ${money(Math.max(500, Math.ceil((c.spent * 1.1) / 500) * 500), currency)}`}>
                <span className="n">{c.category}</span><span className="num">{money(c.spent, currency)}</span><span className="add"><Icon name="plus" />Limit</span>
              </motion.button>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

function BudgetCard({ c, i, currency, today, busy, editing, onEdit, onSave, onOpen }: {
  c: BudgetCategory; i: number; currency: string; today: number | null; busy: boolean; editing: boolean;
  onEdit: () => void; onSave: (name: string, limit: number | null) => Promise<void>; onOpen: () => void;
}) {
  const [draft, setDraft] = useState(c.budget_limit ?? 0);
  useEffect(() => { if (editing) setDraft(c.budget_limit ?? 0); }, [editing, c.budget_limit]);
  const limit = editing ? draft : c.budget_limit ?? 0;
  const status = editing ? statusOf(c.spent, limit || 1, c.projected) : c.status;
  const scale = Math.max(limit, c.spent, today !== null ? c.projected : 0) || 1;
  const spentW = Math.min(100, (c.spent / scale) * 100);
  const paceW = today !== null ? Math.min(100, (c.projected / scale) * 100) : spentW;
  const limitX = (limit / scale) * 100;
  const gap = limit - c.spent;
  const max = Math.max(1000, Math.ceil((Math.max(c.budget_limit ?? 0, c.spent) * 2) / 500) * 500);

  return (
    <motion.article layout className={`bud-card s-${status} ${editing ? "editing" : ""}`}
      initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }}
      transition={{ ...SPRING, delay: Math.min(i, 8) * 0.03 }} whileHover={{ y: -3 }}>
      <div className="top">
        <button className="name" onClick={onOpen}><span className="dot" />{c.category}<Icon name="arrowRight" /></button>
        <button className="edit" onClick={onEdit} aria-label={`Change the ${c.category} limit`} aria-expanded={editing}><Icon name={editing ? "x" : "edit"} /></button>
      </div>
      <div className="fig">
        <span className="num spent">{money(c.spent, currency)}</span>
        <span className="of">of {compact(limit, currency)}</span>
      </div>
      <div className="meter" aria-hidden>
        <motion.i className="pace" initial={false} animate={{ width: `${paceW}%` }} transition={SPRING} />
        <motion.i className="fill" initial={{ width: 0 }} animate={{ width: `${spentW}%` }} transition={{ ...SPRING, delay: 0.1 + Math.min(i, 8) * 0.03 }} />
        <motion.span className="limit" initial={false} animate={{ left: `${Math.min(100, limitX)}%` }} transition={SPRING} />
        {today !== null ? <span className="today" style={{ left: `${Math.min(100, today * limitX)}%` }} title="Where you would be today at an even pace" /> : null}
      </div>
      <div className="foot">
        {gap >= 0 ? <><b>{money(gap, currency)}</b> left</> : <><b className="bad">{money(-gap, currency)}</b> over</>}
        {today !== null && c.projected > limit && gap >= 0 ? <span className="warnline"> · on pace for {compact(c.projected, currency)}</span> : null}
      </div>
      <AnimatePresence initial={false}>
        {editing ? (
          <motion.form className="bud-edit" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={SPRING}
            onSubmit={(e) => { e.preventDefault(); void onSave(c.category, draft > 0 ? draft : null); }}>
            <input type="range" min={0} max={max} step={100} value={draft} onChange={(e) => setDraft(Number(e.target.value))} aria-label="Monthly limit" />
            <div className="row-edit">
              <input className="num" type="number" min={0} step={100} value={draft || ""} placeholder="no limit" onChange={(e) => setDraft(Number(e.target.value) || 0)} />
              <button type="button" className="btn sm ghost" onClick={() => void onSave(c.category, null)} disabled={busy}>Remove</button>
              <motion.button type="submit" className="btn sm primary" disabled={busy} whileTap={{ scale: 0.95 }}>{busy ? <Spinner /> : "Save"}</motion.button>
            </div>
          </motion.form>
        ) : null}
      </AnimatePresence>
    </motion.article>
  );
}
