"""Bank statement parsers: CSV exports and PDF statements (pdfplumber tables, then text lines, then LLM)."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from .common import clean_text, find_date, merchant_from_narration, parse_amount, parse_date
from .models import ParsedTransaction, ParseResult

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "txn date", "transaction date", "tran date", "value date", "value dt", "posting date", "trans date", "txn dt"),
    "description": ("narration", "description", "particulars", "details", "transaction details", "remarks", "transaction remarks",
                    "desc", "memo", "transaction description", "narrative"),
    "debit": ("withdrawal amt.", "withdrawal amt", "withdrawal", "withdrawals", "debit", "debit amount", "dr", "debit amt",
              "paid out", "money out", "withdrawal (dr)", "withdrawal amount", "debit (inr)", "debit(inr)"),
    "credit": ("deposit amt.", "deposit amt", "deposit", "deposits", "credit", "credit amount", "cr", "credit amt", "paid in",
               "money in", "deposit (cr)", "deposit amount", "credit (inr)", "credit(inr)"),
    "amount": ("amount", "amount (inr)", "transaction amount", "amt", "amount (rs.)", "amount(inr)", "txn amount"),
    "type": ("type", "dr/cr", "cr/dr", "transaction type", "debit/credit", "dr / cr", "txn type"),
    "balance": ("balance", "closing balance", "running balance", "available balance", "bal", "balance (inr)", "closing bal"),
    "ref": ("chq./ref.no.", "ref no", "reference", "chq/ref no", "cheque no", "ref", "utr", "chq no", "ref no.", "reference no"),
}


def _norm(h: Any) -> str:
    return re.sub(r"\s+", " ", str(h or "")).strip().lower().replace("\n", " ")


def map_columns(header: list[Any]) -> dict[str, int]:
    cols: dict[str, int] = {}
    normed = [_norm(h) for h in header]
    for role, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(normed):
            if h in aliases and role not in cols and i not in cols.values():
                cols[role] = i
                break
    if "date" not in cols:
        for i, h in enumerate(normed):
            if "date" in h and i not in cols.values():
                cols["date"] = i
                break
    if "description" not in cols:
        for i, h in enumerate(normed):
            if any(k in h for k in ("narration", "descr", "particular", "detail", "remark")) and i not in cols.values():
                cols["description"] = i
                break
    if "debit" not in cols:
        for i, h in enumerate(normed):
            if ("withdraw" in h or "debit" in h) and i not in cols.values():
                cols["debit"] = i
                break
    if "credit" not in cols:
        for i, h in enumerate(normed):
            if ("deposit" in h or "credit" in h) and i not in cols.values():
                cols["credit"] = i
                break
    if "balance" not in cols:
        for i, h in enumerate(normed):
            if "bal" in h and i not in cols.values():
                cols["balance"] = i
                break
    return cols


def is_header(cols: dict[str, int]) -> bool:
    return "date" in cols and ("amount" in cols or "debit" in cols or "credit" in cols)


def rows_to_transactions(header: list[Any], rows: list[list[Any]], source: str, source_name: str | None) -> tuple[list[ParsedTransaction], list[str]]:
    cols = map_columns(header)
    out: list[ParsedTransaction] = []
    warnings: list[str] = []
    if not is_header(cols):
        return out, [f"could not identify date/amount columns in header {header!r}"]

    def cell(row: list[Any], role: str) -> str | None:
        i = cols.get(role)
        if i is None or i >= len(row):
            return None
        return clean_text(row[i])

    for n, row in enumerate(rows, start=1):
        if not row or all(clean_text(c) is None for c in row):
            continue
        iso = parse_date(cell(row, "date") or "")
        if not iso:
            continue  # subtotal / footer rows
        desc = cell(row, "description") or ""
        debit = parse_amount(cell(row, "debit"))
        credit = parse_amount(cell(row, "credit"))
        amount: float | None = None
        direction = "debit"
        if debit:
            amount, direction = abs(debit), "debit"
        elif credit:
            amount, direction = abs(credit), "credit"
        else:
            amt = parse_amount(cell(row, "amount"))
            if amt is None:
                warnings.append(f"row {n}: no amount")
                continue
            typ = (cell(row, "type") or "").lower()
            amt_cell = (cell(row, "amount") or "").lower()
            if amt < 0 or typ.startswith("cr") or "credit" in typ or amt_cell.endswith("cr"):
                direction = "credit"
            elif typ.startswith("dr") or "debit" in typ or amt_cell.endswith("dr"):
                direction = "debit"
            else:
                direction = "credit" if amt < 0 else "debit"
            amount = abs(amt)
        if not amount:
            continue
        raw = " | ".join(str(clean_text(c) or "") for c in row)
        out.append(ParsedTransaction(
            date=iso, amount=round(amount, 2), direction=direction, merchant=merchant_from_narration(desc) if desc else "UNKNOWN",
            description=desc or None, raw_text=raw, source=source, reference=cell(row, "ref"),
            balance_after=parse_amount(cell(row, "balance")),
        ))
    return out, warnings


# ------------------------------------------------------------------ CSV


def parse_csv_text(text: str, source_name: str | None = None) -> ParseResult:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ParseResult(source_kind="csv", source_name=source_name, parser="csv", warnings=["empty file"])
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = list(csv.reader(io.StringIO("\n".join(lines)), dialect))
    header_idx = None
    for i, row in enumerate(reader[:30]):
        if is_header(map_columns(row)):
            header_idx = i
            break
    if header_idx is None:
        return ParseResult(source_kind="csv", source_name=source_name, parser="csv",
                           warnings=["no header row with date and amount columns found"], raw_excerpt="\n".join(lines[:5]))
    header = reader[header_idx]
    body = [r for r in reader[header_idx + 1:] if any(c.strip() for c in r)]
    txs, warnings = rows_to_transactions(header, body, "statement", source_name)
    return ParseResult(source_kind="csv", source_name=source_name, parser="csv", transactions=txs, warnings=warnings,
                       raw_excerpt="\n".join(lines[header_idx:header_idx + 4]))


def parse_csv(path: str | Path) -> ParseResult:
    p = Path(path)
    return parse_csv_text(p.read_text(encoding="utf-8-sig", errors="replace"), p.name)


# ------------------------------------------------------------------ PDF

_LINE = re.compile(
    r"^(?P<date>\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[ \-][A-Za-z]{3}[ \-]\d{2,4})\s+"
    r"(?P<desc>.+?)\s+(?P<amt>\d[\d,]*\.\d{2})\s*(?P<drcr>Dr|Cr|DR|CR|D|C)?(?:\s+(?P<bal>\d[\d,]*\.\d{2})\s*(?P<drcr2>Dr|Cr|DR|CR)?)?\s*$"
)


def parse_pdf_text_lines(text: str, source_name: str | None) -> tuple[list[ParsedTransaction], list[str]]:
    out: list[ParsedTransaction] = []
    warnings: list[str] = []
    prev_balance: float | None = None
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        iso = parse_date(m.group("date"))
        if not iso:
            continue
        amount = parse_amount(m.group("amt")) or 0.0
        bal = parse_amount(m.group("bal"))
        flag = (m.group("drcr") or m.group("drcr2") or "").upper()
        desc = m.group("desc").strip()
        if flag.startswith("C"):
            direction = "credit"
        elif flag.startswith("D"):
            direction = "debit"
        elif bal is not None and prev_balance is not None:
            direction = "credit" if bal > prev_balance else "debit"
        else:
            direction = "credit" if re.search(r"\b(salary|refund|cashback|interest|credited|cr)\b", desc, re.IGNORECASE) else "debit"
        if bal is not None:
            prev_balance = bal
        if amount <= 0:
            continue
        out.append(ParsedTransaction(date=iso, amount=amount, direction=direction, merchant=merchant_from_narration(desc),
                                     description=desc, raw_text=line.strip(), source="statement", balance_after=bal))
    if not out:
        warnings.append("no statement lines matched the text pattern")
    return out, warnings


def parse_pdf(path: str | Path, provider: Any = None) -> ParseResult:
    import pdfplumber

    p = Path(path)
    txs: list[ParsedTransaction] = []
    warnings: list[str] = []
    text_all: list[str] = []
    parser = "pdfplumber-tables"
    with pdfplumber.open(str(p)) as pdf:
        header: list[Any] | None = None
        for page in pdf.pages:
            text_all.append(page.extract_text() or "")
            for table in page.extract_tables() or []:
                if not table:
                    continue
                rows = [r for r in table if r and any(c for c in r)]
                if not rows:
                    continue
                if is_header(map_columns(rows[0])):
                    header, body = rows[0], rows[1:]
                elif header is not None and len(rows[0]) == len(header):
                    body = rows  # continuation table on the next page
                else:
                    continue
                got, w = rows_to_transactions(header, body, "statement", p.name)
                txs.extend(got)
                warnings.extend(w)
    if not txs:
        parser = "pdf-text-lines"
        txs, w = parse_pdf_text_lines("\n".join(text_all), p.name)
        warnings.extend(w)
    if not txs and provider is not None and getattr(provider, "is_llm", False):
        parser = "vision-llm"
        try:
            extracted = provider.extract_transactions_from_pdf(p.read_bytes())
            for e in extracted or []:
                iso = parse_date(e.date) or find_date(e.date or "")
                if not iso or not e.amount:
                    continue
                txs.append(ParsedTransaction(date=iso, amount=abs(e.amount), direction=e.direction, merchant=e.merchant,
                                             description=e.description, raw_text=e.description or e.merchant, source="statement",
                                             confidence=e.confidence))
        except Exception as exc:  # LLM unavailable: report, do not crash the import
            warnings.append(f"LLM extraction failed: {exc}")
    return ParseResult(source_kind="statement", source_name=p.name, parser=parser, transactions=txs, warnings=warnings,
                       raw_excerpt="\n".join(text_all)[:800] or None)
