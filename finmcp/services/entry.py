"""Reading a line the way a person typed it.

The hard part is direction. "890 from company" is money in, "890 to company" is money out, and no list of income
words covers both: the next person will type "bonus", "settled up", "sold the bike", "refund came through". So the
reading is layered, and each layer answers only when it actually knows.

The client reads the grammar itself — that is instant and offline, and it is right most of the time. This module is
what it asks when it is guessing: first what this account has recorded at that merchant before (free, private, and
better the more the ledger holds), and only then the model.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..db.repository import Repository
from ..llm.provider import LLMError, LLMProvider

HINT = ("one line a person typed into their own expense tracker. 'to' or 'at' someone is money out (debit); "
        "'from' someone, or being paid, refunded or reimbursed, is money in (credit)")


@dataclass
class EntryGuess:
    """What a layer was able to say. `direction` is None when nothing knew, and the caller keeps its own reading."""

    direction: str | None = None      # "debit" | "credit"
    merchant: str | None = None
    amount: float | None = None
    confidence: float = 0.0
    source: str = "unknown"           # history | model | unknown

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def from_history(repo: Repository, merchant: str) -> EntryGuess | None:
    """How this account has filed this merchant before. An employer only ever pays you; a shop only ever takes."""
    rows = repo.merchant_history(merchant)
    if not rows:
        return None
    share = sum(1 for r in rows if r["direction"] == "credit") / len(rows)
    if 0.25 < share < 0.75:
        return None  # the account does both at this name, so its history has no opinion worth acting on
    # One earlier entry is a hint; a handful is a habit.
    return EntryGuess(direction="credit" if share >= 0.75 else "debit",
                      confidence=min(0.95, 0.6 + 0.1 * len(rows)), source="history")


def from_model(provider: LLMProvider, text: str) -> EntryGuess | None:
    """Hand the whole line to the model. This is the layer that has never seen the phrasing before and still copes."""
    try:
        found = provider.extract_transactions(text, hint=HINT) or []
    except LLMError:
        return None
    if not found:
        return None
    tx = found[0]
    return EntryGuess(direction=tx.direction, merchant=(tx.merchant or "").strip() or None,
                      amount=tx.amount if tx.amount and tx.amount > 0 else None,
                      confidence=max(0.5, float(tx.confidence)), source="model")


def parse_entry(repo: Repository, provider: LLMProvider, text: str, merchant: str | None = None) -> EntryGuess:
    """The layers in order of what they cost. Returns an empty guess when none of them knows."""
    if merchant:
        remembered = from_history(repo, merchant)
        if remembered is not None:
            return remembered
    return from_model(provider, text) or EntryGuess()
