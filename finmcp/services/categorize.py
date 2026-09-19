"""Categorization pipeline: user memory -> keyword rules -> LLM -> review queue."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..db.repository import Repository, Transaction, merchant_key
from ..llm.provider import LLMError, LLMProvider
from ..taxonomy import match_keywords, resolve_category_name

log = logging.getLogger("finmcp.categorize")

NEEDS_REVIEW_BELOW = 0.6
INCOME_HINTS = ("salary", "payroll", "refund", "cashback", "interest", "int.pd", "dividend", "reimbursement", "bonus", "stipend", "inward")


@dataclass
class Guess:
    category: str | None
    confidence: float
    source: str
    reasoning: str


class Categorizer:
    def __init__(self, repo: Repository, provider: LLMProvider, actor: str = "mcp"):
        self.repo = repo
        self.provider = provider
        self.actor = actor

    # ------------------------------------------------------------------ guessing

    def guess(self, tx: Transaction) -> Guess:
        key = merchant_key(tx.merchant)
        mem = self.repo.recall_merchant(key)
        if mem:
            return Guess(mem["category"], min(0.98, 0.86 + 0.03 * int(mem["hits"])), "memory",
                         f"user previously filed '{tx.merchant}' as {mem['category']}")

        text = f"{tx.merchant} {tx.description or ''}"
        if tx.direction == "credit" and any(h in text.lower() for h in INCOME_HINTS):
            return Guess("Income", 0.9, "rule", "credit with an income keyword")

        hit = match_keywords(text)
        if hit:
            name, kw = hit
            if tx.direction == "credit" and name not in {"Income", "Transfers", "Investments"}:
                # A credit from a shop is almost always a refund.
                return Guess("Income", 0.7, "rule", f"credit from '{kw}' treated as refund")
            in_merchant = kw in tx.merchant.lower()
            return Guess(name, 0.82 if in_merchant else 0.7, "rule", f"keyword '{kw}'")

        if tx.direction == "credit":
            return Guess("Income", 0.55, "rule", "unmatched credit; probably income")

        if self.provider.is_llm:
            try:
                examples = self._memory_examples()
                g = self.provider.categorize(merchant=tx.merchant, description=tx.description, amount=tx.amount,
                                             direction=tx.direction, categories=self.repo.list_categories(), examples=examples)
            except LLMError as exc:
                log.warning("LLM categorization failed: %s", exc)
                g = None
            if g is not None:
                name = resolve_category_name(g.category)
                if name is None:
                    cat = self.repo.get_category(g.category)
                    name = cat.name if cat else None
                if name:
                    return Guess(name, float(g.confidence), "llm", g.reasoning)
        return Guess(None, 0.0, "none", "no memory, rule or model match")

    def _memory_examples(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repo.memory_examples(limit)

    # ------------------------------------------------------------------ applying

    def categorize(self, tx_id: int, force: bool = False) -> dict[str, Any]:
        tx = self.repo.get_transaction(tx_id)
        if tx is None:
            raise ValueError(f"Transaction {tx_id} not found")
        if tx.category_id and tx.category_source == "user" and not force:
            return self._result(tx, changed=False, note="kept: category was set by the user (use force=True to override)")
        g = self.guess(tx)
        category_id = None
        if g.category:
            cat = self.repo.get_category(g.category)
            category_id = cat.id if cat else None
        needs_review = category_id is None or g.confidence < NEEDS_REVIEW_BELOW
        updated = self.repo.update_transaction(
            tx_id, category_id=category_id, category_confidence=round(g.confidence, 3) if category_id else None,
            category_source=g.source if category_id else None, needs_review=needs_review,
        )
        self.repo.audit(self.actor, "categorize", "transaction", tx_id,
                        {"category": g.category, "confidence": g.confidence, "source": g.source, "reasoning": g.reasoning})
        return self._result(updated, changed=True, note=g.reasoning)

    def categorize_many(self, ids: list[int], force: bool = False) -> list[dict[str, Any]]:
        return [self.categorize(i, force=force) for i in ids]

    def apply_user_category(self, tx_id: int, category: str) -> dict[str, Any]:
        tx = self.repo.get_transaction(tx_id)
        if tx is None:
            raise ValueError(f"Transaction {tx_id} not found")
        name = resolve_category_name(category)
        cat = self.repo.get_category(name or category)
        if cat is None:
            raise ValueError(f"Unknown category {category!r}. Known: {', '.join(c.name for c in self.repo.list_categories())}")
        updated = self.repo.update_transaction(tx_id, category_id=cat.id, category_confidence=1.0, category_source="user", needs_review=False)
        self.repo.remember_merchant(merchant_key(tx.merchant), cat.id)
        self.repo.audit(self.actor, "user_categorize", "transaction", tx_id, {"category": cat.name})
        return self._result(updated, changed=True, note="learned from you; future transactions from this merchant will follow")

    @staticmethod
    def _result(tx: Transaction, *, changed: bool, note: str) -> dict[str, Any]:
        return {
            "transaction_id": tx.id, "merchant": tx.merchant, "amount": tx.amount, "direction": tx.direction,
            "category": tx.category, "confidence": tx.category_confidence, "source": tx.category_source,
            "needs_review": tx.needs_review, "changed": changed, "note": note,
        }
