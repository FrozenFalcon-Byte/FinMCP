import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useToast } from "../components/Toast";
import { Avatar, Chip, Empty, ErrorBox, Icon, PageHead, Sheet, Skeleton, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { dayLabel, money } from "../lib/format";
import { useLedger } from "../lib/ledger";
import { PERIODS } from "../lib/periods";
import { useStatus } from "../lib/status";
import type { Category, Transaction, TransactionPage } from "../lib/types";

const PAGE = 60;

export default function Transactions() {
  const { currency } = useStatus();
  const { version, bump } = useLedger();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "last 90 days";
  const category = params.get("category") ?? "";
  const search = params.get("search") ?? params.get("merchant") ?? "";
  const direction = params.get("direction") ?? "";
  const review = params.get("needs_review_only") === "true";
  const [q, setQ] = useState(search);
  const [cats, setCats] = useState<Category[]>([]);
  const [rows, setRows] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    next.delete("merchant");
    setParams(next, { replace: true });
  };

  useEffect(() => { setQ(search); }, [search]);
  useEffect(() => {
    const t = setTimeout(() => { if (q !== search) set("search", q || null); }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  useEffect(() => { api.get<Category[]>("/categories").then(setCats).catch(() => undefined); }, [version]);

  const load = useCallback(async (offset = 0) => {
    setLoading(true);
    try {
      const page = await api.get<TransactionPage>("/transactions", {
        period: period === "all time" ? undefined : period, category: category || undefined, search: search || undefined,
        direction: direction || undefined, needs_review_only: review || undefined, limit: PAGE, offset,
      });
      setRows((prev) => (offset ? [...prev, ...page.transactions] : page.transactions));
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [period, category, search, direction, review]);

  useEffect(() => { void load(0); }, [load, version]);

  const groups = useMemo(() => {
    const m = new Map<string, Transaction[]>();
    for (const t of rows) m.set(t.date, [...(m.get(t.date) ?? []), t]);
    return [...m.entries()];
  }, [rows]);

  const save = async (patch: Record<string, unknown>) => {
    if (!editing) return;
    setBusy(true);
    try {
      await api.patch(`/transactions/${editing.id}`, patch);
      setEditing(null);
      bump();
      if (patch.category) toast(`Filed under ${patch.category}. FinMCP will remember this merchant.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!editing) return;
    const tx = editing;
    setBusy(true);
    try {
      await api.del(`/transactions/${tx.id}`);
      setEditing(null);
      bump();
      toast(`Deleted ${tx.merchant} · ${money(tx.amount, currency)}`, "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };
  const categorizeRest = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ processed: number; categorized: number }>("/transactions/categorize-uncategorized", undefined, { limit: 100 });
      toast(`Categorised ${r.categorized} of ${r.processed}.`);
      bump();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  const expenseCats = cats.filter((c) => c.kind !== "income");

  return (
    <>
      <PageHead title="Transactions" sub={loading && !rows.length ? "Loading…" : `${total.toLocaleString("en-IN")} in ${PERIODS.find((p) => p.value === period)?.label.toLowerCase() ?? period}`}>
        <button className="btn sm" onClick={() => void api.download(`/export.csv${period !== "all time" ? `?period=${encodeURIComponent(period)}` : ""}`, "finmcp-transactions.csv")}><Icon name="download" />CSV</button>
        {review ? <button className="btn sm primary" onClick={() => void categorizeRest()} disabled={busy}><Icon name="wand" />Categorise the rest</button> : null}
      </PageHead>
      <div className="filters">
        <div className="search"><Icon name="search" /><input className="input" placeholder="Search merchant or note" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <select className="select" value={period} onChange={(e) => set("period", e.target.value)}>
          {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        <select className="select" value={category} onChange={(e) => set("category", e.target.value || null)}>
          <option value="">All categories</option>
          {cats.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
        </select>
        <div className="chips">
          <Chip onClick={() => set("direction", direction === "debit" ? null : "debit")} on={direction === "debit"}>Money out</Chip>
          <Chip onClick={() => set("direction", direction === "credit" ? null : "credit")} on={direction === "credit"}>Money in</Chip>
          <Chip onClick={() => set("needs_review_only", review ? null : "true")} on={review} tone="warn">Needs review</Chip>
        </div>
      </div>
      {error ? <ErrorBox>{error}</ErrorBox> : null}
      {loading && !rows.length ? <div className="stack"><Skeleton h={58} /><Skeleton h={58} /><Skeleton h={58} /></div> : null}
      {!loading && !rows.length ? <Empty>Nothing matches. Try a longer period or clear the filters.</Empty> : null}
      {groups.map(([date, items]) => (
        <div className="day-group" key={date}>
          <div className="day-head"><span>{dayLabel(date)}</span><span className="num">{money(items.filter((t) => t.direction === "debit").reduce((s, t) => s + t.amount, 0), currency)}</span></div>
          {items.map((t) => (
            <div className={`tx ${t.needs_review ? "review" : ""}`} key={t.id} onClick={() => setEditing(t)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") setEditing(t); }}>
              <Avatar name={t.merchant} credit={t.direction === "credit"} neutral={t.direction !== "credit"} />
              <div className="grow">
                <div className="t ellipsis">{t.merchant}</div>
                <div className="s">
                  <span>{t.category ?? "uncategorized"}</span>
                  {t.needs_review ? <span className="chip warn" style={{ height: 20, padding: "0 7px", fontSize: 11 }}>review</span> : null}
                  {t.client && !["web", "seed"].includes(t.client) ? <span className="via">via {t.client}</span> : null}
                  {t.description ? <span className="ellipsis" style={{ maxWidth: 260 }}>{t.description}</span> : null}
                </div>
              </div>
              <div className={`amt num ${t.direction === "credit" ? "in" : ""}`}>{t.direction === "credit" ? "+" : ""}{money(t.amount, currency, 2)}</div>
            </div>
          ))}
        </div>
      ))}
      {rows.length < total ? <div style={{ textAlign: "center", marginTop: 12 }}><button className="btn" onClick={() => void load(rows.length)} disabled={loading}>{loading ? <Spinner /> : `Show more (${(total - rows.length).toLocaleString("en-IN")} left)`}</button></div> : null}

      <Sheet open={!!editing} onClose={() => setEditing(null)} title={editing?.merchant ?? ""} sub={editing ? `${dayLabel(editing.date)} · ${money(editing.amount, currency, 2)} · ${editing.direction === "credit" ? "money in" : "money out"}${editing.client ? ` · added via ${editing.client}` : ""}` : ""}
        actions={editing ? (
          <>
            <button className="btn danger" onClick={() => void remove()} disabled={busy}><Icon name="trash" />Delete</button>
            <button className="btn" onClick={() => setEditing(null)}>Close</button>
          </>
        ) : null}>
        {editing ? <EditForm tx={editing} cats={expenseCats.concat(cats.filter((c) => c.kind === "income"))} busy={busy} onSave={save} /> : null}
      </Sheet>
    </>
  );
}

function EditForm({ tx, cats, busy, onSave }: { tx: Transaction; cats: Category[]; busy: boolean; onSave: (patch: Record<string, unknown>) => Promise<void> }) {
  const [merchant, setMerchant] = useState(tx.merchant);
  const [amount, setAmount] = useState(String(tx.amount));
  const [date, setDate] = useState(tx.date);
  const [category, setCategory] = useState(tx.category ?? "");
  const [description, setDescription] = useState(tx.description ?? "");
  const [direction, setDirection] = useState(tx.direction);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const patch: Record<string, unknown> = {};
    if (merchant.trim() && merchant !== tx.merchant) patch.merchant = merchant.trim();
    if (Number(amount) > 0 && Number(amount) !== tx.amount) patch.amount = Number(amount);
    if (date !== tx.date) patch.date = date;
    if (direction !== tx.direction) patch.direction = direction;
    if ((category || null) !== (tx.category || null)) patch.category = category || "uncategorized";
    if (description !== (tx.description ?? "")) patch.description = description;
    if (tx.needs_review && category) patch.needs_review = false;
    if (!Object.keys(patch).length) return;
    void onSave(patch);
  };
  return (
    <form onSubmit={submit} className="stack" style={{ gap: 14 }}>
      {tx.needs_review ? <div className="notice" style={{ padding: "10px 14px", borderRadius: 12, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 13 }}>Low confidence. Pick a category and FinMCP learns this merchant.</div> : null}
      <div className="form-grid">
        <div className="field full"><label>Category</label>
          <select className="select" value={category} onChange={(e) => setCategory(e.target.value)} autoFocus>
            <option value="">Uncategorized</option>
            {cats.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </div>
        <div className="field full"><label>Merchant</label><input className="input" value={merchant} onChange={(e) => setMerchant(e.target.value)} /></div>
        <div className="field"><label>Amount</label><input className="input num" type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
        <div className="field"><label>Date</label><input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div className="field"><label>Direction</label>
          <select className="select" value={direction} onChange={(e) => setDirection(e.target.value as "debit" | "credit")}><option value="debit">Money out</option><option value="credit">Money in</option></select>
        </div>
        <div className="field full"><label>Note</label><input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" /></div>
      </div>
      {tx.raw_text ? <div className="small muted mono" style={{ wordBreak: "break-all" }}>{tx.raw_text}</div> : null}
      <button className="btn primary" type="submit" disabled={busy}>{busy ? <Spinner /> : <><Icon name="check" />Save</>}</button>
    </form>
  );
}
