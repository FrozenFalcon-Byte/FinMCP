import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Avatar, Chip, Empty, ErrorBox, Icon, Ring, Skeleton, Sparkline, Stat } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { compact, dayLabel, greeting, money, monthLabel } from "../lib/format";
import { useStatus } from "../lib/status";
import type { Overview, Summary } from "../lib/types";
import { useApi } from "../lib/useApi";

function first(name: string): string {
  return name.trim().split(/\s+/)[0] || "there";
}

export default function Home() {
  const { user } = useAuth();
  const { currency } = useStatus();
  const navigate = useNavigate();
  const ov = useApi(() => api.get<Overview>("/overview"), []);
  const daily = useApi(() => api.get<Summary>("/summary", { period: "last 30 days", group_by: "day" }), []);

  const spark = useMemo(() => {
    const rows = daily.data?.breakdown ?? [];
    const byDay = new Map(rows.map((r) => [r.day as string, r.spent]));
    const out: { d: string; v: number }[] = [];
    const end = new Date();
    for (let i = 29; i >= 0; i--) {
      const d = new Date(end);
      d.setDate(end.getDate() - i);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      out.push({ d: key, v: byDay.get(key) ?? 0 });
    }
    return out;
  }, [daily.data]);

  const o = ov.data;
  const pace = o?.pace_pct;
  const sts = o?.safe_to_spend;

  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="page-head" style={{ marginBottom: 4 }}>
        <div>
          <h1>{greeting()}, {first(user?.name ?? "there")}.</h1>
          <div className="sub">{o ? `${o.month.label} · day ${o.month.day} of ${o.month.days}` : " "}</div>
        </div>
      </div>

      {ov.error ? <ErrorBox>{ov.error}</ErrorBox> : null}

      <section className="card hero-card">
        <div className="between" style={{ alignItems: "flex-start" }}>
          <div>
            <div className="label">Spent this month</div>
            <div className="big num">{o ? <Stat value={o.spent} format={(n) => money(n, currency)} /> : <Skeleton h={44} w={220} />}</div>
            <div className="pace">
              {o && pace !== null && pace !== undefined ? (
                <Chip tone={pace <= 0 ? "good" : "warn"}><Icon name={pace <= 0 ? "arrowDown" : "arrowUp"} />{Math.abs(pace).toFixed(0)}% vs this point last month</Chip>
              ) : o ? <Chip>first month on record</Chip> : null}
              {o && o.alerts.count ? <Link to="/app/budgets" className="chip bad" style={{ textDecoration: "none" }}>{o.alerts.count} budget {o.alerts.count === 1 ? "alert" : "alerts"}</Link> : null}
              {o && o.needs_review ? <Link to="/app/transactions?needs_review_only=true" className="chip warn" style={{ textDecoration: "none" }}>{o.needs_review} to review</Link> : null}
            </div>
            {o?.insights.length ? <p className="insight">{o.insights.find((i) => i.kind === "mover")?.text ?? o.insights.find((i) => i.kind !== "pace")?.text ?? o.insights[0].text}</p> : null}
          </div>
          {sts?.per_day != null ? (
            <Ring pct={sts.used_pct ?? 0} size={104} stroke={10}>
              <b className="num">{sts.used_pct != null ? `${Math.round(sts.used_pct)}%` : "—"}</b>
              <span>of budget</span>
            </Ring>
          ) : null}
        </div>
        {spark.length && daily.data ? <Sparkline values={spark.map((p) => p.v)} labels={spark.map((p) => p.d)} /> : <Skeleton h={76} style={{ marginTop: 18 }} />}
        <div className="mini-stats">
          <div className="mini accent">
            <div className="k">Safe to spend</div>
            <div className="v num">{sts?.per_day != null ? `${money(Math.max(0, sts.per_day), currency)} / day` : "—"}</div>
            <div className="s">{sts?.basis === "budget" ? `${money(Math.max(0, sts.left ?? 0), currency)} left of ${compact(sts.budget_total ?? 0, currency)}` : sts?.basis === "average" ? "based on your 3-month average" : "set budgets to see this"}</div>
          </div>
          <div className="mini">
            <div className="k">Coming up</div>
            <div className="v num">{o ? money(o.upcoming.reduce((s, u) => s + u.amount, 0), currency) : "—"}</div>
            <div className="s">{o ? `${o.upcoming.length} bill${o.upcoming.length === 1 ? "" : "s"} in the next 2 weeks` : ""}</div>
          </div>
          <div className="mini">
            <div className="k">Received</div>
            <div className="v num">{o ? money(o.received, currency) : "—"}</div>
            <div className="s">{o ? `${o.month.days_left} day${o.month.days_left === 1 ? "" : "s"} left this month` : ""}</div>
          </div>
        </div>
      </section>

      <div className="grid two">
        <section className="card">
          <div className="card-head"><h2>Where it went</h2><Link to="/app/budgets" className="card-link">Budgets <Icon name="arrowRight" /></Link></div>
          {o ? (o.spent > 0 ? <WhereItWent o={o} currency={currency} onPick={(c) => navigate(`/app/transactions?category=${encodeURIComponent(c)}&period=this%20month`)} />
            : <Empty>Nothing spent yet this month.</Empty>) : <div className="stack"><Skeleton h={150} /><Skeleton /></div>}
        </section>

        <section className="card">
          <div className="card-head"><h2>Coming up</h2><Link to="/app/subscriptions" className="card-link">Subscriptions <Icon name="arrowRight" /></Link></div>
          {o ? (o.upcoming.length ? (
            <div className="list clickable">
              {o.upcoming.slice(0, 4).map((u) => (
                <Link className="item" key={u.key} to={`/app/transactions?merchant=${encodeURIComponent(u.merchant)}`}>
                  <Avatar name={u.merchant} neutral />
                  <div className="grow"><div className="t">{u.merchant}</div><div className="s">{u.status === "overdue" ? "expected, not seen yet" : u.days_until === 0 ? "due today" : u.days_until === 1 ? "due tomorrow" : `in ${u.days_until} days`} · {u.cadence}</div></div>
                  <div className="amt num">{money(u.amount, currency)}</div>
                </Link>
              ))}
            </div>
          ) : <Empty>No recurring bills detected yet. They appear after three regular payments.</Empty>) : <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div>}
        </section>
      </div>

      {o?.goals.length ? (
        <section className="card">
          <div className="card-head"><h2>Goals</h2><Link to="/app/goals" className="card-link">All goals <Icon name="arrowRight" /></Link></div>
          <div className="grid three">
            {o.goals.slice(0, 3).map((g) => (
              <div className="goal-card" key={g.id}>
                <Ring pct={g.progress_pct ?? 0} size={64} stroke={7} tone=""><b className="num" style={{ fontSize: 13 }}>{Math.round(g.progress_pct ?? 0)}%</b></Ring>
                <div className="grow"><div className="strong ellipsis">{g.icon ? `${g.icon} ` : ""}{g.name}</div><div className="small muted num">{compact(g.saved, currency)} of {compact(g.target, currency)}</div></div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head"><h2>Recent</h2><Link to="/app/transactions" className="card-link">All transactions <Icon name="arrowRight" /></Link></div>
        {o ? (o.recent.length ? (
          <div className="list clickable">
            {o.recent.map((t) => (
              <Link className="item" key={t.id} to={`/app/transactions?search=${encodeURIComponent(t.merchant)}`}>
                <Avatar name={t.merchant} credit={t.direction === "credit"} neutral={t.direction !== "credit"} />
                <div className="grow"><div className="t">{t.merchant}</div><div className="s">{dayLabel(t.date)} · {t.category ?? "uncategorized"}{t.client && t.client !== "web" && t.client !== "seed" ? ` · via ${t.client}` : ""}</div></div>
                <div className={`amt num ${t.direction === "credit" ? "in" : ""}`}>{t.direction === "credit" ? "+" : ""}{money(t.amount, currency)}</div>
              </Link>
            ))}
          </div>
        ) : <Empty>Add your first expense in the bar above, or import a statement.</Empty>) : <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div>}
      </section>
      {o ? <div className="small muted" style={{ textAlign: "center" }}>Previous month to date: {money(o.previous_spent, currency)} · {monthLabel(o.month.key, { month: "long", year: "numeric" })}</div> : null}
    </div>
  );
}

/* Where this month's money went: one ring, the four biggest categories and the rest, each labelled beside it.
   Hovering a slice or a row shows its amount in the middle; a row opens those transactions. */
const SLICE_COLORS = ["#4d43fe", "#0f9488", "#d9892b", "#d6455d"];
const REST_COLOR = "#c9ccd8";

function WhereItWent({ o, currency, onPick }: { o: Overview; currency: string; onPick: (category: string) => void }) {
  const [hot, setHot] = useState<number | null>(null);
  const top = o.top_categories.slice(0, 4);
  const rest = Math.max(0, o.spent - top.reduce((a, c) => a + c.spent, 0));
  const parts = [
    ...top.map((c, i) => ({ name: c.category ?? "Uncategorized", value: c.spent, color: SLICE_COLORS[i], limit: c.budget_limit ?? null, pick: c.category ?? "" })),
    ...(rest >= 1 ? [{ name: "Everything else", value: rest, color: REST_COLOR, limit: null, pick: null }] : []),
  ];
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const R = 62;
  const C = 2 * Math.PI * R;
  const GAP = parts.length > 1 ? 3 : 0;
  let at = 0;
  const focus = hot !== null ? parts[hot] : null;
  return (
    <div className="where">
      <div className="donut-wrap">
        <svg viewBox="0 0 160 160" className="donut" role="img" aria-label={`Spent ${money(o.spent, currency)} this month`}>
          <circle cx="80" cy="80" r={R} className="donut-track" />
          <g transform="rotate(-90 80 80)">
            {parts.map((p, i) => {
              const len = (p.value / total) * C;
              const offset = -at;
              at += len;
              return (
                <motion.circle key={p.name} cx="80" cy="80" r={R} fill="none" stroke={p.color} strokeLinecap="butt"
                  initial={{ strokeDasharray: `0 ${C}` }} animate={{ strokeDasharray: `${Math.max(0.1, len - GAP)} ${C}`, strokeWidth: hot === i ? 22 : 16, opacity: hot === null || hot === i ? 1 : 0.35 }}
                  transition={{ duration: 0.7, delay: 0.08 * i, ease: [0.22, 1, 0.36, 1] }} strokeDashoffset={offset}
                  onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)} style={{ cursor: p.pick !== null ? "pointer" : "default" }}
                  onClick={() => { if (p.pick !== null) onPick(p.pick); }} />
              );
            })}
          </g>
        </svg>
        <div className="donut-c">
          <b className="num">{money(focus ? focus.value : o.spent, currency)}</b>
          <span>{focus ? focus.name : "spent this month"}</span>
        </div>
      </div>
      <div className="where-list">
        {parts.map((p, i) => {
          const over = p.limit ? p.value - p.limit : 0;
          return (
            <button type="button" key={p.name} className={`where-row ${hot === i ? "hot" : ""}`} disabled={p.pick === null}
              onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)} onFocus={() => setHot(i)} onBlur={() => setHot(null)}
              onClick={() => { if (p.pick !== null) onPick(p.pick); }}>
              <span className="dot" style={{ background: p.color }} />
              <span className="n">{p.name}{over > 0 ? <em>{money(over, currency)} over budget</em> : null}</span>
              <span className="pct">{Math.round((p.value / total) * 100)}%</span>
              <span className="v num">{money(p.value, currency)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
