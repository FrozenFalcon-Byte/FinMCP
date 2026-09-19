"""Aggregations: spend summaries, budget vs actual, and budget alerts."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from ..db.repository import Repository
from .periods import Period, month_bounds, resolve_period


def _round(v: float | None) -> float:
    return round(float(v or 0), 2)


def get_summary(repo: Repository, period: str | None = None, group_by: str = "category", top: int = 15, today: date | None = None) -> dict[str, Any]:
    p: Period = resolve_period(period, today)
    start, end = p.start.isoformat(), p.end.isoformat()
    totals = repo.totals(start, end)
    spent = _round(totals["spent"])
    out: dict[str, Any] = {
        "period": p.as_dict(),
        "totals": {
            "spent": spent,
            "transfers_out": _round(totals["transfers_out"]),
            "received": _round(totals["received"]),
            "net": _round(float(totals["received"] or 0) - float(totals["spent"] or 0) - float(totals["transfers_out"] or 0)),
            "transaction_count": int(totals["n"] or 0),
            "uncategorized_count": int(totals["uncategorized"] or 0),
            "avg_daily_spend": _round(spent / p.days) if p.days else 0.0,
        },
        "group_by": group_by,
        "breakdown": [],
    }
    if group_by == "category":
        cats = {c.name: c for c in repo.list_categories()}
        rows = repo.spend_by_category(start, end)
        for r in rows:
            cat = cats.get(r["category"])
            share = (float(r["total"]) / spent * 100) if spent and r["kind"] != "transfer" else None
            entry: dict[str, Any] = {
                "category": r["category"], "kind": r["kind"], "spent": _round(r["total"]), "count": int(r["n"]),
                "largest": _round(r["largest"]), "share_pct": round(share, 1) if share is not None else None,
            }
            if cat and cat.budget_limit:
                entry["budget_limit"] = cat.budget_limit
                entry["budget_used_pct"] = round(float(r["total"]) / cat.budget_limit * 100, 1)
            out["breakdown"].append(entry)
        out["breakdown"] = out["breakdown"][:top]
    elif group_by == "merchant":
        for r in repo.top_merchants(start, end, n=top):
            out["breakdown"].append({"merchant": r["merchant"], "category": r["category"], "spent": _round(r["total"]), "count": int(r["n"])})
    elif group_by in {"day", "week", "month"}:
        credits = {r["bucket"]: r for r in repo.series(start, end, bucket=group_by, direction="credit")}
        buckets = {r["bucket"]: r for r in repo.series(start, end, bucket=group_by)}
        for key in sorted(set(buckets) | set(credits)):
            debit, credit = buckets.get(key), credits.get(key)
            out["breakdown"].append({
                group_by: key, "spent": _round(debit["total"] if debit else 0), "count": int(debit["n"]) if debit else 0,
                "received": _round(credit["total"] if credit else 0), "credit_count": int(credit["n"]) if credit else 0,
            })
    else:
        raise ValueError("group_by must be one of: category, merchant, day, week, month")
    income = repo.spend_by_category(start, end, direction="credit")
    out["income_breakdown"] = [{"category": r["category"], "received": _round(r["total"]), "count": int(r["n"])} for r in income]
    return out


def get_budget_summary(repo: Repository, month: str | None = None, today: date | None = None) -> dict[str, Any]:
    """Budget vs actual for one calendar month, with a straight-line projection for the current month."""
    today = today or date.today()
    if month:
        p = resolve_period(month, today)
        s, e = month_bounds(p.start.year, p.start.month)
    else:
        s, e = month_bounds(today.year, today.month)
    days_in_month = calendar.monthrange(s.year, s.month)[1]
    is_current = s <= today <= e
    days_elapsed = (today - s).days + 1 if is_current else days_in_month
    window_end = min(e, today) if is_current else e
    rows = {r["category"]: r for r in repo.spend_by_category(s.isoformat(), window_end.isoformat())}
    items: list[dict[str, Any]] = []
    total_budget = 0.0
    total_spent_budgeted = 0.0
    for cat in repo.list_categories():
        if cat.kind != "expense":
            continue
        spent = _round(rows.get(cat.name, {}).get("total", 0))
        projected = _round(spent / days_elapsed * days_in_month) if is_current and days_elapsed else spent
        item: dict[str, Any] = {"category": cat.name, "spent": spent, "count": int(rows.get(cat.name, {}).get("n", 0)), "projected": projected}
        if cat.budget_limit:
            total_budget += cat.budget_limit
            total_spent_budgeted += spent
            pct = spent / cat.budget_limit * 100
            item.update({
                "budget_limit": cat.budget_limit, "remaining": _round(cat.budget_limit - spent), "used_pct": round(pct, 1),
                "projected_pct": round(projected / cat.budget_limit * 100, 1),
                "status": "exceeded" if spent > cat.budget_limit else "warning" if pct >= 80 else "on_track",
            })
        else:
            item["status"] = "no_budget"
        items.append(item)
    order = {"exceeded": 0, "warning": 1, "on_track": 2, "no_budget": 3}
    items.sort(key=lambda i: (order[i["status"]], -i["spent"]))
    return {
        "month": s.strftime("%Y-%m"), "label": s.strftime("%B %Y"), "is_current_month": is_current,
        "days_elapsed": days_elapsed, "days_in_month": days_in_month,
        "totals": {"budget": _round(total_budget), "spent_in_budgeted": _round(total_spent_budgeted),
                   "remaining": _round(total_budget - total_spent_budgeted),
                   "used_pct": round(total_spent_budgeted / total_budget * 100, 1) if total_budget else None},
        "categories": items,
    }


def check_budget_alerts(repo: Repository, month: str | None = None, warn_at_pct: float = 80.0, today: date | None = None) -> dict[str, Any]:
    """Categories at or over their limit, plus those on pace to exceed it by month end."""
    summary = get_budget_summary(repo, month, today)
    alerts: list[dict[str, Any]] = []
    for c in summary["categories"]:
        if "budget_limit" not in c:
            continue
        if c["status"] == "exceeded":
            level, msg = "exceeded", f"{c['category']} is over budget: spent {c['spent']:,.0f} of {c['budget_limit']:,.0f} ({c['used_pct']:.0f}%)."
        elif c["used_pct"] >= warn_at_pct:
            level, msg = "warning", f"{c['category']} has used {c['used_pct']:.0f}% of its {c['budget_limit']:,.0f} budget with {c['remaining']:,.0f} left."
        elif summary["is_current_month"] and c["projected_pct"] >= 100 and c["count"] >= 2:
            level, msg = "pace", f"{c['category']} is on pace to reach {c['projected']:,.0f}, above its {c['budget_limit']:,.0f} budget."
        else:
            continue
        alerts.append({"level": level, "category": c["category"], "spent": c["spent"], "budget_limit": c["budget_limit"],
                       "used_pct": c["used_pct"], "projected": c["projected"], "remaining": c["remaining"], "message": msg})
    return {"month": summary["month"], "label": summary["label"], "alert_count": len(alerts), "alerts": alerts,
            "checked_at": (today or date.today()).isoformat()}
