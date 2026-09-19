"""EMIs: fixed monthly instalments on a loan. Everything here follows from the schedule (first instalment date,
amount, tenure): how many are paid, what is still owed, when the next one is due and when the loan ends."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any

from ..db.repository import Emi, Repository


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def emi_status(e: Emi, today: date) -> dict[str, Any]:
    start = date.fromisoformat(e.start_date)
    paid = 0
    while paid < e.tenure_months and add_months(start, paid) <= today:
        paid += 1
    left = e.tenure_months - paid
    total = e.amount * e.tenure_months
    next_due = add_months(start, paid) if left else None
    return {
        **e.model_dump(),
        "paid_count": paid,
        "left_count": left,
        "progress_pct": round(paid / e.tenure_months * 100, 1),
        "paid_total": round(e.amount * paid, 2),
        "outstanding": round(e.amount * left, 2),
        "total_payable": round(total, 2),
        "interest": round(total - e.principal, 2) if e.principal else None,
        "next_due": next_due.isoformat() if next_due else None,
        "days_until": (next_due - today).days if next_due else None,
        "ends_on": add_months(start, e.tenure_months - 1).isoformat(),
        "closed": left == 0,
    }


def emi_report(repo: Repository, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    items = [emi_status(e, today) for e in repo.list_emis()]
    items.sort(key=lambda i: (i["closed"], i["next_due"] or "9999"))
    active = [i for i in items if not i["closed"]]
    return {
        "count": len(active),
        "monthly_total": round(sum(i["amount"] for i in active), 2),
        "outstanding": round(sum(i["outstanding"] for i in active), 2),
        "next": active[0] if active else None,
        "items": items,
    }
