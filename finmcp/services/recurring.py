"""Recurring payment detection: subscriptions, bills, SIPs, rent.

Pure function over the debit history: groups by normalised merchant, looks at the gaps between payments, and keeps
the merchants whose gaps cluster on a known cadence. Amount stability is reported, not required (electricity bills
vary; they are still bills)."""
from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ..db.repository import Repository, merchant_key

CADENCES: tuple[tuple[str, int, int, int, int, float, float], ...] = (
    # name, days, min gap, max gap, min occurrences, min regularity, max amount spread
    # Short cadences must have a stable amount: weekly groceries are a habit, a weekly plan is a subscription.
    ("weekly", 7, 6, 8, 4, 0.7, 0.15),
    ("fortnightly", 14, 12, 16, 3, 0.7, 0.15),
    ("monthly", 30, 26, 35, 3, 0.6, 0.6),
    ("quarterly", 91, 84, 98, 2, 0.5, 0.3),
    ("yearly", 365, 350, 380, 2, 0.5, 0.3),
)


def _cadence_for(gap: float) -> tuple[str, int, int, float, float] | None:
    for name, days, lo, hi, min_n, min_regular, max_spread in CADENCES:
        if lo <= gap <= hi:
            return name, days, min_n, min_regular, max_spread
    return None


def _add_months(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def next_due_after(last: date, cadence: str, days: int) -> date:
    """Bills keep their day of the month; short cadences just add days."""
    if cadence == "monthly":
        return _add_months(last, 1)
    if cadence == "quarterly":
        return _add_months(last, 3)
    if cadence == "yearly":
        return _add_months(last, 12)
    return last + timedelta(days=days)


def detect_recurring(rows: list[dict[str, Any]], today: date | None = None, *, min_occurrences: int = 3) -> list[dict[str, Any]]:
    today = today or date.today()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = merchant_key(r["merchant"])
        if key:
            groups[key].append(r)

    found: list[dict[str, Any]] = []
    for key, items in groups.items():
        # one payment per day per merchant: same-day repeats are split orders, not separate bills
        by_day: dict[str, dict[str, Any]] = {}
        for r in items:
            d = str(r["date"])
            if d in by_day:
                by_day[d]["amount"] = float(by_day[d]["amount"]) + float(r["amount"])
                by_day[d]["ids"].append(int(r["id"]))
            else:
                by_day[d] = {**r, "amount": float(r["amount"]), "ids": [int(r["id"])]}
        series = sorted(by_day.values(), key=lambda r: r["date"])
        if len(series) < min(min_occurrences, 2):
            continue
        dates = [date.fromisoformat(str(r["date"])) for r in series]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
        median_gap = statistics.median(gaps)
        cadence = _cadence_for(median_gap)
        if cadence is None:
            continue
        name, days, min_n, min_regular, max_spread = cadence
        if len(series) < max(min_n, min_occurrences if name not in {"quarterly", "yearly"} else min_n):
            continue
        tolerance = max(3, round(days * 0.2))
        regular = sum(1 for g in gaps if abs(g - days) <= tolerance) / len(gaps)
        if regular < min_regular:
            continue
        amounts = [r["amount"] for r in series]
        amount = statistics.median(amounts)
        spread = (statistics.median([abs(a - amount) for a in amounts]) / amount) if amount else 0.0
        if spread > max_spread:
            continue
        last = series[-1]
        last_date = dates[-1]
        next_due = next_due_after(last_date, name, days)
        days_until = (next_due - today).days
        if days_until < -days:  # a whole cycle missed: probably cancelled
            continue
        status = "overdue" if days_until < -2 else "due" if days_until <= 3 else "upcoming"
        found.append({
            "key": key,
            "merchant": last["merchant"],
            "category": last.get("category"),
            "category_kind": last.get("category_kind") or "expense",
            "cadence": name,
            "cadence_days": days,
            "amount": round(amount, 2),
            "amount_varies": spread > 0.15,
            "last_amount": round(float(last["amount"]), 2),
            "last_date": last_date.isoformat(),
            "next_due": next_due.isoformat(),
            "days_until": days_until,
            "status": status,
            "occurrences": len(series),
            # What this bill has actually cost, counted from the payments themselves rather than from the cadence.
            "first_date": dates[0].isoformat(),
            "paid_total": round(sum(float(a) for a in amounts), 2),
            "paid_12m": round(sum(float(r["amount"]) for r, d in zip(series, dates, strict=True) if (today - d).days <= 365), 2),
            "paid_this_year": round(sum(float(r["amount"]) for r, d in zip(series, dates, strict=True) if d.year == today.year), 2),
            "count_this_year": sum(1 for d in dates if d.year == today.year),
            "regularity": round(regular, 2),
            "monthly_cost": round(amount * 30.4375 / days, 2),
            "transaction_ids": [i for r in series[-3:] for i in r["ids"]],
        })
    found.sort(key=lambda r: (r["days_until"], -r["amount"]))
    return found


CADENCE_DAYS: dict[str, int] = {name: days for name, days, *_ in CADENCES}


def _declared(rule: dict[str, Any], history: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """An item for a bill the account wrote down itself.

    Detection reads a rhythm out of history; this reads it off the instruction. The numbers underneath are still
    counted from real payments to that merchant — there may be none yet, and a row that says "paid 0×" is the
    honest answer for a bill that has only been declared."""
    key = str(rule["merchant_key"])
    paid = sorted((r for r in history if merchant_key(r["merchant"]) == key), key=lambda r: str(r["date"]))
    dates = [date.fromisoformat(str(r["date"])) for r in paid]
    amounts = [float(r["amount"]) for r in paid]
    cadence, days = str(rule["cadence"]), int(rule["cadence_days"])
    next_due = date.fromisoformat(str(rule["next_due"]))
    days_until = (next_due - today).days
    last = paid[-1] if paid else None
    return {
        "key": key,
        "merchant": str(rule["merchant"]),
        "category": rule.get("category") or (last.get("category") if last else None),
        "category_kind": (last.get("category_kind") if last else None) or "expense",
        "cadence": cadence,
        "cadence_days": days,
        "amount": round(float(rule["amount"]), 2),
        "amount_varies": False,
        "last_amount": round(amounts[-1], 2) if amounts else round(float(rule["amount"]), 2),
        "last_date": dates[-1].isoformat() if dates else None,
        "next_due": next_due.isoformat(),
        "days_until": days_until,
        "status": "overdue" if days_until < -2 else "due" if days_until <= 3 else "upcoming",
        "occurrences": len(paid),
        "first_date": dates[0].isoformat() if dates else None,
        "paid_total": round(sum(amounts), 2),
        "paid_12m": round(sum(a for a, d in zip(amounts, dates, strict=True) if (today - d).days <= 365), 2),
        "paid_this_year": round(sum(a for a, d in zip(amounts, dates, strict=True) if d.year == today.year), 2),
        "count_this_year": sum(1 for d in dates if d.year == today.year),
        "regularity": 1.0,
        "monthly_cost": round(float(rule["amount"]) * 30.4375 / days, 2),
        "transaction_ids": [int(r["id"]) for r in paid[-3:]],
        "declared": True,
    }


def list_recurring(repo: Repository, today: date | None = None, *, days: int = 400) -> dict[str, Any]:
    today = today or date.today()
    history = repo.debit_history(days)
    items = detect_recurring(history, today)
    # Standing instructions are stitched on rather than detected: the list stays a reading of history, and autopay
    # is what the account has said about it. A rule with no rhythm behind it — a bill written down by hand, or one
    # whose payments have not built a pattern yet — becomes an item of its own, marked as declared.
    standing = repo.list_autopay()
    rules = {str(r["merchant_key"]): {
        "active": bool(r["active"]), "amount": float(r["amount"]), "next_due": str(r["next_due"]),
        "posted_count": int(r["posted_count"]), "last_posted_on": str(r["last_posted_on"]) if r["last_posted_on"] else None,
    } for r in standing}
    seen = {str(i["key"]) for i in items}
    items += [_declared(r, history, today) for r in standing if str(r["merchant_key"]) not in seen]
    for item in items:
        item["autopay"] = rules.get(str(item["key"]))
        item.setdefault("declared", False)
    items.sort(key=lambda r: (r["days_until"], -r["amount"]))
    expenses = [i for i in items if i["category_kind"] != "transfer"]
    on_autopay = [i for i in items if i.get("autopay") and i["autopay"]["active"]]
    return {
        "count": len(items),
        "autopay_count": len(on_autopay),
        "autopay_monthly": round(sum(i["monthly_cost"] for i in on_autopay), 2),
        "paid_12m": round(sum(i["paid_12m"] for i in expenses), 2),
        "monthly_total": round(sum(i["monthly_cost"] for i in items), 2),
        "monthly_expenses": round(sum(i["monthly_cost"] for i in expenses), 2),
        "upcoming": [i for i in items if -2 <= i["days_until"] <= 14],
        "items": items,
        "checked_at": today.isoformat(),
    }
