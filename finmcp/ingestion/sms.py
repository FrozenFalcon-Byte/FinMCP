"""UPI / bank SMS parser. Regex library for the common Indian bank formats, LLM cleanup for the rest."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from .common import clean_text, find_date, parse_date
from .models import ParsedTransaction, ParseResult

AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹|rupees)\s*([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
DEBIT_WORDS = ("debited", "spent", "paid", "sent", "withdrawn", "purchase of", "txn of", "transaction of", "charged")
CREDIT_WORDS = ("credited", "received", "deposited", "refunded", "refund of", "reversed", "cashback of")
SKIP_PATTERNS = (
    (r"\botp\b|one[- ]time password|verification code", "otp"),
    (r"will be debited|is due|due on|due date|emi of|overdue|reminder", "reminder"),
    (r"payment request|has requested|requested money|requesting|collect request", "payment request"),
    (r"\boffer\b|cashback up ?to|upto|apply now|download|click|t&c|limited time|earn up|win\b|congratulations", "promotion"),
    (r"failed|declined|unsuccessful|could not be processed|not processed|timed out", "failed transaction"),
    (r"statement is ready|e-statement|your statement", "statement notice"),
    (r"kyc|pan card|aadhaar|update your", "service notice"),
)
DATE_RE = re.compile(
    r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[ \-]?[A-Za-z]{3}[ \-]?\d{2,4})\b"
)
MERCHANT_PATTERNS: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"\bto\s+VPA\s+([A-Za-z0-9._\-]+)@", re.IGNORECASE), 0.9),
    (re.compile(r"\bto\s+([A-Za-z0-9._\-]+)@[A-Za-z]{2,}", re.IGNORECASE), 0.85),
    (re.compile(r"\bby\s+(?:a/c\s+linked\s+to\s+)?VPA\s+([A-Za-z0-9._\-]+)@", re.IGNORECASE), 0.9),
    (re.compile(r";\s*([A-Za-z0-9&.'\- ]+?)\s+credited", re.IGNORECASE), 0.9),
    (re.compile(r"\bat\s+([A-Za-z0-9&.'*\-][A-Za-z0-9&.'*\- ]{1,50}?)\s+on\s+\d", re.IGNORECASE), 0.9),
    (re.compile(r"\bto\s+([A-Za-z0-9&.'*\-][A-Za-z0-9&.'*\- ]{1,50}?)(?=\s+on\s+\d|\s+via\b|\s+using\b|\s*[.;,(]|\s+ref\b|\s+upi\b|$)", re.IGNORECASE), 0.85),
    (re.compile(r"\b(?:from|by)\s+(?:NEFT|IMPS|RTGS|UPI)?\s*(?:from\s+)?([A-Z][A-Za-z0-9&.'\-]+(?:\s+[A-Za-z0-9&.'\-]+){0,4}?)(?=\s+on\s+\d|\s*[.;,(]|\s+ref\b|$)"), 0.8),
    (re.compile(r"\b(?:info|towards|for)[:\s]+([A-Za-z0-9&.'\-][A-Za-z0-9&.'\- ]{1,50}?)(?=\s+on\s+\d|\s*[.;,(]|\s+ref\b|\s+via\b|$)", re.IGNORECASE), 0.7),
    (re.compile(r"-\s*([A-Za-z0-9&.'\-][A-Za-z0-9&.'\- ]{1,40}?)\s*\.\s*(?:avl|available|bal)", re.IGNORECASE), 0.7),
)
ACCOUNT_RE = re.compile(r"(?:a/c|acct|account|card|ac)\s*(?:no\.?)?\s*[Xx*]*(\d{3,4})\b", re.IGNORECASE)
_TRAILING_NOISE = re.compile(r"\b(?:via|using|through)\s+\w+.*$|\b(?:ref|upi ref|utr|txn)\b.*$", re.IGNORECASE)


def skip_reason(text: str) -> str | None:
    low = text.lower()
    for pattern, reason in SKIP_PATTERNS:
        if re.search(pattern, low):
            return reason
    return None


def _first_index(low: str, words: tuple[str, ...]) -> int:
    idx = [low.find(w) for w in words if w in low]
    return min(idx) if idx else -1


def parse_sms(text: str, fallback_date: str | None = None) -> tuple[ParsedTransaction | None, str | None]:
    """Parse one message. Returns (transaction, None) or (None, reason)."""
    t = clean_text(text) or ""
    if len(t) < 15:
        return None, "too short"
    reason = skip_reason(t)
    if reason:
        return None, reason
    low = t.lower()
    d_idx, c_idx = _first_index(low, DEBIT_WORDS), _first_index(low, CREDIT_WORDS)
    if d_idx < 0 and c_idx < 0:
        return None, "no debit/credit keyword"
    direction = "credit" if (c_idx >= 0 and (d_idx < 0 or c_idx < d_idx)) else "debit"
    # the first amount is the transaction; later ones are balances / limits
    am = AMOUNT_RE.search(t)
    if not am:
        am2 = re.search(r"\b(\d[\d,]*\.\d{2})\b", t)
        if not am2:
            return None, "no amount"
        amount = float(am2.group(1).replace(",", ""))
    else:
        amount = float(am.group(1).replace(",", ""))
    if amount <= 0:
        return None, "zero amount"
    dm = DATE_RE.search(t)
    iso = parse_date(dm.group(1)) if dm else None
    if not iso:
        iso = find_date(t) or fallback_date or date.today().isoformat()
    merchant, confidence = None, 0.5
    for pattern, conf in MERCHANT_PATTERNS:
        m = pattern.search(t)
        if m:
            cand = _TRAILING_NOISE.sub("", m.group(1)).strip(" .,-:;")
            cand = re.sub(r"\s+", " ", cand)
            if cand and cand.lower() not in {"your", "you", "a/c", "account", "the"}:
                merchant, confidence = cand, conf
                break
    if merchant is None:
        acct = ACCOUNT_RE.search(t)
        merchant = f"Unknown ({'a/c ' + acct.group(1) if acct else 'sms'})"
    return ParsedTransaction(date=iso, amount=amount, direction=direction, merchant=merchant.upper() if merchant.islower() else merchant,
                             description=t[:200], raw_text=t, source="sms", confidence=confidence), None


def split_messages(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) == 1 and blocks[0].count("\n") >= 2:
        blocks = [ln.strip() for ln in blocks[0].splitlines() if ln.strip()]
    return blocks


def parse_sms_dump(text: str, source_name: str | None = None, provider: Any = None, fallback_date: str | None = None) -> ParseResult:
    txs: list[ParsedTransaction] = []
    skipped: list[str] = []
    warnings: list[str] = []
    unparsed: list[str] = []
    for msg in split_messages(text):
        tx, why = parse_sms(msg, fallback_date)
        if tx:
            if tx.confidence < 0.7:
                unparsed.append(msg)
            txs.append(tx)
        else:
            skipped.append(f"{why}: {msg[:70]}")
    parser = "sms-regex"
    if unparsed and provider is not None and getattr(provider, "is_llm", False):
        parser = "sms-regex+llm"
        try:
            fixed = provider.extract_transactions("\n".join(unparsed), hint="bank SMS alerts") or []
            by_raw = {tx.raw_text: tx for tx in txs}
            for e in fixed:
                iso = parse_date(e.date) or find_date(e.date or "")
                for tx in by_raw.values():
                    if abs(tx.amount - abs(e.amount)) < 0.01 and tx.confidence < 0.7:
                        tx.merchant = e.merchant or tx.merchant
                        tx.confidence = max(tx.confidence, e.confidence)
                        if iso:
                            tx.date = iso
                        break
        except Exception as exc:
            warnings.append(f"LLM cleanup failed: {exc}")
    return ParseResult(source_kind="sms", source_name=source_name, parser=parser, transactions=txs, warnings=warnings, skipped=skipped)
