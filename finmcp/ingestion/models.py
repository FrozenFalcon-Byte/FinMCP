"""Normalised output of every parser."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..db.repository import fingerprint_for


class LineItem(BaseModel):
    name: str
    quantity: float | None = None
    unit_price: float | None = None
    total: float | None = None


class ParsedTransaction(BaseModel):
    date: str = Field(description="ISO date")
    amount: float = Field(gt=0)
    direction: str = "debit"
    merchant: str
    description: str | None = None
    raw_text: str
    source: str = "statement"          # receipt | statement | csv | sms
    confidence: float = 1.0
    line_items: list[LineItem] = Field(default_factory=list)
    reference: str | None = None
    balance_after: float | None = None

    @property
    def fingerprint(self) -> str:
        return fingerprint_for(self.date, self.amount, self.direction, self.merchant, self.raw_text)


class ParseResult(BaseModel):
    source_kind: str
    source_name: str | None = None
    parser: str
    transactions: list[ParsedTransaction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    raw_excerpt: str | None = None

    @property
    def count(self) -> int:
        return len(self.transactions)
