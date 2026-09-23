"""Month over month: what the ledger looks like when you stand back from it.

Everywhere else in the app answers "what is happening now" — this answers "is it getting better or worse", which
is a different question and needs a different shape of data: one row per month, one row per category across those
months, and the few sentences a person would actually say about the picture.

Two rules run through it. Transfers are not spending, so they are left out of every total the same way
`Repository.totals` leaves them out. And the month in progress is never quietly compared against whole ones: it is
marked `partial`, carries a straight-line `projected`, and anything that compares it says which of the two it used.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from ..db.repository import Repository

MAX_MONTHS = 24
TOP_CATEGORIES = 8


def _round(v: float | None) -> float:
    return round(float(v or 0), 2)


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _keys(months: int, today: date) -> list[str]:
    """The calendar months the report covers, oldest first, ending with the one we are in."""
    out = []
    for back in range(months - 1, -1, -1):
        y, m = _shift(today.year, today.month, -back)
        out.append(f"{y:04d}-{m:02d}")
    return out


def _label(key: str, long: bool = False) -> str:
    y, m = int(key[:4]), int(key[5:7])
    return f"{calendar.month_name[m]} {y}" if long else calendar.month_abbr[m]


def _pct(now: float, before: float) -> float | None:
    """Percent change, or None when there is nothing to change from — a jump off zero is not a percentage."""
    if before <= 0:
        return None
    return round((now - before) / before * 100, 1)


def get_trends(repo: Repository, months: int = 6, today: date | None = None, top: int = TOP_CATEGORIES) -> dict[str, Any]:
    """Spending and income by month, the categories behind it, and what moved."""
    today = today or date.today()
    months = max(2, min(MAX_MONTHS, int(months)))
    keys = _keys(months, today)
    rows = repo.monthly_rollup(keys[0])

    # One pass: the month series, and the category-by-month matrix behind it.
    blank = {"spent": 0.0, "received": 0.0, "count": 0}
    by_month: dict[str, dict[str, float]] = {k: dict(blank) for k in keys}
    by_category: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r["month"])
        if key not in by_month:
            continue  # a month before the window, or a future-dated entry
        spent = float(r["spent"] or 0) if r["category_kind"] != "transfer" else 0.0
        received = float(r["received"] or 0)
        slot = by_month[key]
        slot["spent"] += spent
        slot["received"] += received
        slot["count"] += int(r["n"] or 0)
        if spent <= 0:
            continue
        cat = by_category.setdefault(str(r["category"]), {"category": str(r["category"]), "kind": str(r["category_kind"]),
                                                          "months": {k: 0.0 for k in keys}, "total": 0.0})
        cat["months"][key] += spent
        cat["total"] += spent

    current = keys[-1]
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    elapsed = today.day

    series: list[dict[str, Any]] = []
    for key in keys:
        slot = by_month[key]
        partial = key == current and elapsed < days_in_month
        projected = _round(slot["spent"] / elapsed * days_in_month) if partial and elapsed else _round(slot["spent"])
        series.append({
            "month": key, "label": _label(key), "long_label": _label(key, long=True),
            "spent": _round(slot["spent"]), "received": _round(slot["received"]),
            "net": _round(slot["received"] - slot["spent"]), "count": int(slot["count"]),
            "partial": partial, "projected": projected,
        })

    complete = [m for m in series if not m["partial"]]
    with_data = [m for m in series if m["count"]]
    spent_total = sum(m["spent"] for m in series)
    received_total = sum(m["received"] for m in series)
    basis = [m for m in complete if m["count"]]
    average = _round(sum(m["spent"] for m in basis) / len(basis)) if basis else 0.0

    totals = {
        "spent": _round(spent_total), "received": _round(received_total), "net": _round(received_total - spent_total),
        "average_spent": average, "months_with_data": len(with_data),
        "saved_pct": round((received_total - spent_total) / received_total * 100, 1) if received_total > 0 else None,
        "highest": max(basis, key=lambda m: m["spent"])["month"] if basis else None,
        "lowest": min(basis, key=lambda m: m["spent"])["month"] if basis else None,
    }

    # Categories: the biggest by total, each with its own row across the window and where it is heading.
    ordered = sorted(by_category.values(), key=lambda c: -c["total"])
    kept, rest = ordered[:top], ordered[top:]
    now_key = current if by_month[current]["count"] else (complete[-1]["month"] if complete else current)
    now_is_partial = now_key == current and elapsed < days_in_month
    categories: list[dict[str, Any]] = []
    for c in kept:
        history = [c["months"][k] for k in keys if k != now_key]
        seen = [v for v in history if v > 0]
        before = _round(sum(seen) / len(seen)) if seen else 0.0
        now = c["months"][now_key]
        compared = _round(now / elapsed * days_in_month) if now_is_partial and elapsed else _round(now)
        categories.append({
            "category": c["category"], "kind": c["kind"], "total": _round(c["total"]),
            "average": before, "latest": _round(now), "compared": compared,
            "change": _round(compared - before), "change_pct": _pct(compared, before),
            "share_pct": round(c["total"] / spent_total * 100, 1) if spent_total else None,
            "months": {k: _round(v) for k, v in c["months"].items()},
        })
    if rest:
        merged = {k: _round(sum(c["months"][k] for c in rest)) for k in keys}
        categories.append({"category": "Everything else", "kind": "expense", "total": _round(sum(c["total"] for c in rest)),
                           "average": None, "latest": merged[now_key], "compared": merged[now_key], "change": None,
                           "change_pct": None, "share_pct": round(sum(c["total"] for c in rest) / spent_total * 100, 1) if spent_total else None,
                           "months": merged, "aggregate": True})

    movers = [c for c in categories if c.get("change_pct") is not None and abs(c["change"]) >= 1]
    movers.sort(key=lambda c: -abs(c["change"]))
    return {
        "months": months, "window": {"from": keys[0], "to": keys[-1]},
        "compare_month": now_key, "compare_is_projected": now_is_partial,
        "series": series, "totals": totals, "categories": categories,
        "movers": movers[:5],
        "insights": _insights(series, complete, totals, movers, now_key, now_is_partial),
    }


def _insights(series: list[dict[str, Any]], complete: list[dict[str, Any]], totals: dict[str, Any],
              movers: list[dict[str, Any]], now_key: str, projected: bool) -> list[dict[str, Any]]:
    """The two or three sentences a person would say looking at the chart. Each one has to be true of this data."""
    out: list[dict[str, Any]] = []
    run = [m for m in complete if m["count"]]
    if len(run) >= 3:
        last3 = run[-3:]
        if last3[0]["spent"] > last3[1]["spent"] > last3[2]["spent"]:
            out.append({"kind": "streak", "tone": "good", "text": f"Spending has fallen three months running, down to {last3[2]['spent']:,.0f} in {_label(last3[2]['month'], long=True)}."})
        elif last3[0]["spent"] < last3[1]["spent"] < last3[2]["spent"]:
            out.append({"kind": "streak", "tone": "warn", "text": f"Spending has climbed three months running, up to {last3[2]['spent']:,.0f} in {_label(last3[2]['month'], long=True)}."})
    if movers:
        m = movers[0]
        word = "up" if m["change"] > 0 else "down"
        when = "on pace to be" if projected else ""
        out.append({"kind": "mover", "tone": "warn" if m["change"] > 0 else "good",
                    "text": f"{m['category']} is {when + ' ' if when else ''}{word} {abs(m['change_pct']):.0f}% on its usual {m['average']:,.0f} a month."})
    if totals["saved_pct"] is not None:
        pct, n = totals["saved_pct"], totals["months_with_data"]
        span = "this month" if n <= 1 else f"these {n} months"
        # Under a point either way is not a story about saving: it is a story about breaking even, and rounding it
        # to "0%" would say the opposite of what the number means.
        text = (f"You kept {pct:.0f}% of what came in over {span}." if pct >= 1
                else f"You spent {abs(pct):.0f}% more than came in over {span}." if pct <= -1
                else f"You spent almost exactly what came in over {span}.")
        out.append({"kind": "saved", "tone": "good" if pct >= 1 else "warn" if pct <= -1 else "", "text": text})
    if len(run) >= 2 and totals["highest"] and totals["highest"] != now_key:
        high = next(m for m in series if m["month"] == totals["highest"])
        out.append({"kind": "peak", "tone": "", "text": f"{high['long_label']} was the heaviest month at {high['spent']:,.0f}."})
    return out[:3]
