import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Chip, Empty, ErrorBox, Icon, PageHead, Skeleton, Stat } from "../components/ui";
import { api } from "../lib/api";
import { compact, money, monthLabel, num, signed } from "../lib/format";
import { useStatus } from "../lib/status";
import type { TrendCategory, TrendMonth, Trends } from "../lib/types";
import { useApi } from "../lib/useApi";

const RANGES = [3, 6, 12] as const;
const EASE = [0.22, 1, 0.36, 1] as const;

/** Months are the unit here, so the page is read left to right: the window, what it cost, and what moved inside it. */
export default function Reports() {
  const { currency } = useStatus();
  const [months, setMonths] = useState<number>(6);
  const rep = useApi(() => api.get<Trends>("/trends", { months }), [months]);
  const t = rep.data;
  const [hot, setHot] = useState<number | null>(null);

  // The reading is whatever is pointed at, and the newest month when nothing is.
  const shown = t ? (hot !== null ? t.series[hot] : t.series[t.series.length - 1]) : null;

  return (
    <div className="stack" style={{ gap: 18 }}>
      <PageHead title="Reports" sub={t ? `${monthLabel(t.window.from, { month: "long", year: "numeric" })} to ${monthLabel(t.window.to, { month: "long", year: "numeric" })}` : "How the months compare."}>
        <div className="seg" role="group" aria-label="How far back to look">
          {RANGES.map((r) => (
            <button key={r} type="button" className={months === r ? "on" : ""} onClick={() => { setMonths(r); setHot(null); }} aria-pressed={months === r}>
              {months === r ? <motion.span layoutId="seg-pill" className="pill" transition={{ type: "spring", stiffness: 480, damping: 38 }} /> : null}
              <span>{r}m</span>
            </button>
          ))}
        </div>
        <button className="btn sm" onClick={() => t && downloadReport(t, currency)} disabled={!t}><Icon name="download" />CSV</button>
      </PageHead>

      {rep.error ? <ErrorBox>{rep.error}</ErrorBox> : null}

      <section className="card rep-card">
        {t ? (
          <>
            <div className="rep-top">
              <div className="rep-fig">
                <span className="k">Spent over {t.months} months</span>
                <span className="v num"><Stat value={t.totals.spent} format={(n) => money(n, currency)} /></span>
                <span className="s">{money(t.totals.average_spent, currency)} a month on average</span>
              </div>
              <div className="rep-legend">
                <span><i className="sw out" />Spent</span>
                <span><i className="sw in" />Received</span>
              </div>
            </div>

            <Chart series={t.series} currency={currency} hot={hot} onHot={setHot} />

            {shown ? <Readout m={shown} currency={currency} /> : null}
          </>
        ) : <div className="stack"><Skeleton h={54} /><Skeleton h={190} /></div>}
      </section>

      {t?.insights.length ? (
        <div className="rep-notes">
          {t.insights.map((i, n) => (
            <motion.p key={i.text} className={`rep-note ${i.tone}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * n, duration: 0.35, ease: EASE }}>
              <Icon name={i.tone === "good" ? "arrowDown" : i.tone === "warn" ? "arrowUp" : "spark"} />{i.text}
            </motion.p>
          ))}
        </div>
      ) : null}

      <div className="grid two">
        <section className="card">
          <div className="card-head">
            <h2>What moved</h2>
            <span className="meta">{t?.compare_is_projected ? "this month, on pace" : "latest month"} vs its own average</span>
          </div>
          {t ? (t.movers.length ? (
            <div className="list">
              {t.movers.map((c, i) => <Mover key={c.category} c={c} currency={currency} i={i} />)}
            </div>
          ) : <Empty>Nothing has moved far enough from its own average to be worth calling out.</Empty>) : <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div>}
        </section>

        <section className="card">
          <div className="card-head"><h2>Month by month</h2><span className="meta">{t ? `${num(t.series.reduce((s, m) => s + m.count, 0))} entries` : ""}</span></div>
          {t ? (
            <div className="list">
              {[...t.series].reverse().map((m) => (
                <div className="item" key={m.month}>
                  <div className="grow">
                    <div className="t">{m.long_label}{m.partial ? <span className="tag quiet">so far</span> : null}</div>
                    <div className="s">{num(m.count)} entries · received {money(m.received, currency)}</div>
                  </div>
                  <div className="right">
                    <div className="amt num">{money(m.spent, currency)}</div>
                    <div className={`micro num ${m.net >= 0 ? "good" : "bad"}`}>{m.net >= 0 ? "kept " : "short "}{money(Math.abs(m.net), currency)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="stack"><Skeleton /><Skeleton /><Skeleton /></div>}
        </section>
      </div>

      <section className="card">
        <div className="card-head"><h2>Every category, every month</h2><Link to="/app/budgets" className="card-link">Budgets <Icon name="arrowRight" /></Link></div>
        {t ? (t.categories.length ? <Matrix t={t} currency={currency} /> : <Empty>Nothing spent in this window yet.</Empty>) : <Skeleton h={220} />}
      </section>
    </div>
  );
}

/** The bars. Heights are percentages of the tallest month, so the chart fits whatever box it is given — there is
    no pixel width anywhere in it, and the same markup reads at 320px and at 1600px. */
function Chart({ series, currency, hot, onHot }: { series: TrendMonth[]; currency: string; hot: number | null; onHot: (i: number | null) => void }) {
  const top = Math.max(1, ...series.map((m) => Math.max(m.spent, m.received, m.partial ? m.projected : 0)));
  return (
    <div className="rep-chart" onPointerLeave={() => onHot(null)}>
      <div className="rep-rules" aria-hidden="true">
        {[1, 0.5, 0].map((f) => <span key={f} style={{ bottom: `${f * 100}%` }}><b>{compact(top * f, currency)}</b></span>)}
      </div>
      <div className="rep-plot">
        {series.map((m, i) => (
          <button type="button" key={m.month} className={`rep-col ${hot === i ? "hot" : ""}`}
            onPointerEnter={() => onHot(i)} onFocus={() => onHot(i)} onBlur={() => onHot(null)}
            aria-label={`${m.long_label}: spent ${money(m.spent, currency)}, received ${money(m.received, currency)}`}>
            <span className="rep-bars">
              <motion.i className={`rep-bar out ${m.partial ? "partial" : ""}`} initial={{ height: 0 }} animate={{ height: `${(m.spent / top) * 100}%` }} transition={{ duration: 0.65, delay: 0.04 * i, ease: EASE }} />
              <motion.i className="rep-bar in" initial={{ height: 0 }} animate={{ height: `${(m.received / top) * 100}%` }} transition={{ duration: 0.65, delay: 0.04 * i + 0.06, ease: EASE }} />
              {m.partial && m.projected > m.spent ? <motion.i className="rep-pace" initial={{ opacity: 0 }} animate={{ opacity: 1, bottom: `${(m.projected / top) * 100}%` }} transition={{ delay: 0.5, duration: 0.4 }} title="on pace for" /> : null}
            </span>
            <span className="rep-x">{m.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** One line under the chart saying what is being pointed at. A line beats a floating tooltip on a phone: it never
    hangs off an edge and it never covers the bar it is describing. */
function Readout({ m, currency }: { m: TrendMonth; currency: string }) {
  return (
    <div className="rep-read">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={m.month} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
          <b>{m.long_label}</b>
          <span>spent <b className="num">{money(m.spent, currency)}</b></span>
          <span>received <b className="num">{money(m.received, currency)}</b></span>
          <span className={m.net >= 0 ? "good" : "bad"}>{m.net >= 0 ? "kept" : "short"} <b className="num">{money(Math.abs(m.net), currency)}</b></span>
          {m.partial ? <Chip>part month · on pace for {compact(m.projected, currency)}</Chip> : null}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

function Mover({ c, currency, i }: { c: TrendCategory; currency: string; i: number }) {
  const up = (c.change ?? 0) > 0;
  return (
    <motion.div className="item" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.05 * i, duration: 0.3, ease: EASE }}>
      <span className={`mover-arrow ${up ? "up" : "down"}`}><Icon name={up ? "arrowUp" : "arrowDown"} /></span>
      <div className="grow">
        <div className="t">{c.category}</div>
        <div className="s">usually {money(c.average ?? 0, currency)} a month</div>
      </div>
      <div className="right">
        <div className={`amt num ${up ? "bad" : "good"}`}>{signed(c.change_pct ?? 0)}</div>
        <div className="micro muted num">{money(c.compared, currency)}</div>
      </div>
    </motion.div>
  );
}

/** Every category against every month. It scrolls sideways rather than shrinking the columns to nothing: a number
    you cannot read is worse than one you have to reach for. */
function Matrix({ t, currency }: { t: Trends; currency: string }) {
  const keys = t.series.map((m) => m.month);
  const peak = useMemo(() => Math.max(1, ...t.categories.flatMap((c) => keys.map((k) => c.months[k] ?? 0))), [t, keys]);
  return (
    <div className="rep-matrix-wrap">
      <table className="rep-matrix">
        <thead>
          <tr>
            <th scope="col">Category</th>
            {t.series.map((m) => <th key={m.month} scope="col" className="num">{m.label}{m.partial ? "*" : ""}</th>)}
            <th scope="col" className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {t.categories.map((c) => (
            <tr key={c.category} className={c.aggregate ? "rest" : ""}>
              <th scope="row"><span className="n">{c.category}</span>{c.share_pct != null ? <span className="sh">{c.share_pct.toFixed(0)}%</span> : null}</th>
              {keys.map((k) => {
                const v = c.months[k] ?? 0;
                return (
                  <td key={k} className="num cell">
                    <span className="heat" style={{ opacity: v ? 0.08 + (v / peak) * 0.5 : 0 }} />
                    <span className="f">{v ? compact(v, currency) : "—"}</span>
                  </td>
                );
              })}
              <td className="num strong">{compact(c.total, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {t.series.some((m) => m.partial) ? <p className="micro muted" style={{ marginTop: 10 }}>* the month still in progress.</p> : null}
    </div>
  );
}

/** The same report, as a file. Built here from what is already on screen, so it always matches what you are reading. */
function downloadReport(t: Trends, currency: string): void {
  const esc = (v: string | number) => (typeof v === "string" && /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : String(v));
  const keys = t.series.map((m) => m.month);
  const lines = [
    [`FinMCP report`, `${t.window.from} to ${t.window.to}`, currency].map(esc).join(","),
    "",
    ["Month", "Spent", "Received", "Net", "Entries", "In progress"].join(","),
    ...t.series.map((m) => [m.month, m.spent, m.received, m.net, m.count, m.partial ? "yes" : "no"].map(esc).join(",")),
    "",
    ["Category", ...keys, "Total", "Average", "Change %"].map(esc).join(","),
    ...t.categories.map((c) => [c.category, ...keys.map((k) => c.months[k] ?? 0), c.total, c.average ?? "", c.change_pct ?? ""].map(esc).join(",")),
  ];
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `finmcp-report-${t.window.from}-to-${t.window.to}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
