"""The home screen in one call: what a person wants to know about their money before they dig deeper."""
from __future__ import annotations

import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

from ..db.repository import Repository
from .emis import emi_report
from .periods import month_bounds
from .recurring import list_recurring
from .summary import _round, check_budget_alerts, get_budget_summary, get_summary


def _same_window_last_month(today: date) -> tuple[str, str]:
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    s, e = month_bounds(y, m)
    return s.isoformat(), min(e, date(y, m, min(today.day, calendar.monthrange(y, m)[1]))).isoformat()


def get_overview(repo: Repository, today: date | None = None, *, currency: str = "INR") -> dict[str, Any]:
    today = today or date.today()
    month_start, month_end = month_bounds(today.year, today.month)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = max(0, (month_end - today).days)

    prev_s, prev_e = _same_window_last_month(today)
    # The reads are independent, so they run side by side, each in its own short transaction: against a database
    # that is a long round trip away this is the difference between seconds and tens of seconds.
    with ThreadPoolExecutor(max_workers=10, thread_name_prefix="overview") as pool:
        f_this = pool.submit(get_summary, repo, "this month", "category", top=6, today=today)
        f_prev = pool.submit(get_summary, repo, f"{prev_s}..{prev_e}", "category", top=50, today=today)
        f_budget = pool.submit(get_budget_summary, repo, None, today=today)
        f_alerts = pool.submit(check_budget_alerts, repo, None, today=today)
        f_recurring = pool.submit(list_recurring, repo, today)
        f_recent = pool.submit(repo.list_transactions, limit=6)
        f_goals = pool.submit(repo.list_goals)
        f_emis = pool.submit(emi_report, repo, today)
        f_review = pool.submit(repo.list_transactions, needs_review_only=True, limit=1)
        f_three = pool.submit(get_summary, repo, "last 3 months", "category", top=1, today=today)
        f_largest = pool.submit(repo.list_transactions, start=month_start.isoformat(), end=today.isoformat(), direction="debit",
                                order="amount_desc", limit=1)
        this, prev, budget, alerts = f_this.result(), f_prev.result(), f_budget.result(), f_alerts.result()
        recurring, (recent, _), goals, (_, review) = f_recurring.result(), f_recent.result(), f_goals.result(), f_review.result()
        three, (largest_rows, _) = f_three.result(), f_largest.result()
        emis = f_emis.result()

    spent = this["totals"]["spent"]
    prev_spent = prev["totals"]["spent"]
    pace_pct = round((spent - prev_spent) / prev_spent * 100, 1) if prev_spent else None

    # Safe to spend: what is left of the month's budget, spread over the remaining days.
    budget_total = budget["totals"]["budget"]
    if budget_total:
        left = budget["totals"]["remaining"]
        basis = "budget"
    else:
        baseline = three["totals"]["spent"] / 3 if three["totals"]["spent"] else 0.0
        left = baseline - spent
        basis = "average" if baseline else "none"
    per_day = _round(left / (days_left + 1)) if basis != "none" else None

    # Biggest mover versus the same point last month.
    prev_by_cat = {b["category"]: b["spent"] for b in prev["breakdown"]}
    movers = []
    for b in this["breakdown"]:
        if b.get("kind") == "transfer":
            continue
        before = prev_by_cat.get(b["category"], 0.0)
        movers.append({"category": b["category"], "spent": b["spent"], "before": before, "delta": _round(b["spent"] - before)})
    movers.sort(key=lambda m: -abs(m["delta"]))
    top_categories = [b for b in this["breakdown"] if b.get("kind") != "transfer"][:4]
    largest = largest_rows[0] if largest_rows else None

    insights: list[dict[str, Any]] = []
    if pace_pct is not None:
        insights.append({"kind": "pace", "tone": "good" if pace_pct <= 0 else "warn",
                         "text": f"{'Down' if pace_pct <= 0 else 'Up'} {abs(pace_pct):.0f}% versus this point last month."})
    if movers and abs(movers[0]["delta"]) >= max(500, 0.05 * max(spent, 1)):
        m = movers[0]
        insights.append({"kind": "mover", "tone": "warn" if m["delta"] > 0 else "good", "category": m["category"],
                         "text": f"{m['category']} is {'up' if m['delta'] > 0 else 'down'} {abs(m['delta']):,.0f} on last month."})
    if largest is not None and largest.category_kind != "transfer":
        insights.append({"kind": "largest", "tone": "neutral", "transaction_id": largest.id,
                         "text": f"Largest expense: {largest.merchant} ({largest.amount:,.0f}) on {largest.date}."})
    if alerts["alert_count"]:
        a = alerts["alerts"][0]
        insights.append({"kind": "budget", "tone": "bad" if a["level"] == "exceeded" else "warn", "category": a["category"], "text": a["message"]})

    return {
        "today": today.isoformat(),
        "currency": currency,
        "month": {"key": month_start.strftime("%Y-%m"), "label": month_start.strftime("%B %Y"), "day": today.day, "days": days_in_month, "days_left": days_left},
        "spent": spent,
        "received": this["totals"]["received"],
        "net": this["totals"]["net"],
        "transaction_count": this["totals"]["transaction_count"],
        "previous_spent": prev_spent,
        "pace_pct": pace_pct,
        "safe_to_spend": {"per_day": per_day, "left": _round(left) if basis != "none" else None, "basis": basis,
                          "budget_total": budget_total or None, "used_pct": budget["totals"]["used_pct"]},
        "top_categories": top_categories,
        "movers": movers[:3],
        "insights": insights[:3],
        "alerts": {"count": alerts["alert_count"], "items": alerts["alerts"][:3]},
        "upcoming": recurring["upcoming"][:5],
        "emi": {k: emis[k] for k in ("count", "monthly_total", "outstanding", "next")},
        "recurring_monthly": recurring["monthly_expenses"],
        "recurring_count": recurring["count"],
        "recent": [t.model_dump() for t in recent],
        "goals": [g.model_dump() | {"progress_pct": round(min(100.0, g.saved / g.target * 100), 1) if g.target else 0.0} for g in goals[:4]],
        "needs_review": review,
        "week_end": (today + timedelta(days=6 - today.weekday())).isoformat(),
    }
