import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Avatar, Bar, Chip, Empty, ErrorBox, Icon, Ring, Skeleton, Sparkline, Stat } from "../components/ui";
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
          {o ? (o.top_categories.length ? o.top_categories.map((c) => (
            <div className="bud-row" key={c.category} role="button" tabIndex={0} style={{ cursor: "pointer" }} onClick={() => navigate(`/app/transactions?category=${encodeURIComponent(c.category ?? "")}&period=this%20month`)}>
              <div className="n">{c.category}</div>
              <div className="v num">{money(c.spent, currency)}{c.budget_limit ? ` of ${compact(c.budget_limit, currency)}` : c.share_pct != null ? ` · ${Math.round(c.share_pct)}%` : ""}</div>
              <Bar pct={c.budget_limit ? (c.spent / c.budget_limit) * 100 : (c.share_pct ?? 0)} thin tone={c.budget_limit ? undefined : ""} />
            </div>
          )) : <Empty>Nothing spent yet this month.</Empty>) : <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div>}
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
