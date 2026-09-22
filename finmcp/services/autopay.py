"""Autopay: bills that file themselves.

The subscription list is detected from history and nobody edits it. Autopay is the one thing you *can* say about a
detected bill — "this one is on a standing instruction, stop making me type it" — and this is what acts on that.

Two rules keep it honest. It only ever writes a cycle whose date has already passed, so nothing is filed before it
is actually charged; and every entry carries the same fingerprint the importer would give it, so when the real
statement lands the bank's copy is recognised as the same payment rather than doubling it up.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..db.repository import Repository, fingerprint_for
from .recurring import next_due_after

MAX_CATCH_UP = 6   # cycles filed in one run: a rule left alone for a year should not write twelve entries at once


def _iso(d: date) -> str:
    return d.isoformat()


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def run_autopay(repo: Repository, today: date | None = None) -> dict[str, Any]:
    """File every cycle that has come due. Safe to call as often as you like: a cycle already in the ledger is
    recognised by its fingerprint and skipped, and the rule still moves on."""
    now = today or date.today()
    posted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for rule in repo.due_autopay(_iso(now)):
        due = _as_date(rule["next_due"])
        cycles = 0
        while due <= now and cycles < MAX_CATCH_UP:
            cycles += 1
            when = _iso(due)
            amount = float(rule["amount"])
            merchant = str(rule["merchant"])
            print_ = fingerprint_for(when, amount, "debit", merchant)
            category = repo.get_category(str(rule["category"])) if rule.get("category") else None
            tx = repo.insert_transaction(
                date=when, amount=amount, merchant=merchant, direction="debit",
                description="Autopay", category_id=category.id if category else None,
                # The category is the one this account has always filed that merchant under, which is what
                # "memory" means everywhere else in the ledger. `source` is where the entry came from.
                category_source="memory" if category else None, category_confidence=1.0 if category else None,
                source="autopay", fingerprint=print_, ignore_duplicate=True,
            )
            nxt = next_due_after(due, str(rule["cadence"]), int(rule["cadence_days"]))
            if nxt <= due:                      # a cadence that cannot move forward would spin here
                nxt = due + timedelta(days=max(1, int(rule["cadence_days"])))
            repo.advance_autopay(int(rule["id"]), next_due=_iso(nxt), posted_on=when if tx else None)
            (posted if tx else skipped).append({"merchant": merchant, "date": when, "amount": amount})
            due = nxt

    if posted:
        repo.audit("autopay", "post", "autopay", None, {"posted": len(posted), "on": _iso(now)})
    return {
        "ran_at": _iso(now),
        "posted": posted,
        "posted_count": len(posted),
        "already_there": skipped,
        "skipped_count": len(skipped),
    }
