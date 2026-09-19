"""A deterministic natural-language -> SQL translator for common personal-finance questions.

It is the offline fallback for `query_transactions` when no LLM is configured. It handles the
question shapes people actually ask (totals, counts, top merchants/categories, listings, largest
purchases) and refuses anything else with a clear message rather than guessing.
"""
from __future__ import annotations

import re
from datetime import date

from ..services.periods import Period, find_period_in_text, resolve_period
from ..taxonomy import ALIASES, CATEGORY_NAMES, DEFAULT_CATEGORIES


class UnsupportedQuestion(ValueError):
    pass


_STOP = {"the", "my", "me", "i", "a", "an", "of", "in", "on", "at", "for", "to", "from", "with", "did", "do", "have", "has",
         "was", "were", "is", "are", "and", "or", "all", "any", "much", "many", "how", "what", "which", "list", "show",
         "spend", "spent", "spending", "pay", "paid", "buy", "bought", "money", "total", "transactions", "transaction",
         "purchases", "purchase", "expenses", "expense", "this", "last", "month", "week", "year", "days", "day", "top",
         "biggest", "largest", "most", "highest", "expensive", "average", "avg", "count", "number", "over", "under",
         "above", "below", "than", "more", "less", "by", "per", "each", "vs", "versus", "compared", "rs", "inr", "rupees"}

_MERCHANT_KEYWORDS = sorted(
    {kw.strip() for spec in DEFAULT_CATEGORIES for kw in spec.keywords if len(kw.strip()) >= 4 and kw.strip() not in ALIASES},
    key=len, reverse=True,
)
_ALIAS_KEYS = sorted(set(ALIASES) | {n.lower() for n in CATEGORY_NAMES}, key=len, reverse=True)


def _parse_amount(token: str) -> float:
    t = token.replace(",", "").replace("₹", "").strip().lower()
    mult = 1.0
    if t.endswith("k"):
        mult, t = 1000.0, t[:-1]
    elif t.endswith("l") or t.endswith("lakh"):
        mult, t = 100000.0, t.rstrip("lakh").rstrip("l")
    return float(t) * mult


def _money(expr: str) -> str:
    return f"ROUND(({expr})::numeric, 2)"


def rule_based_sql(question: str, today: date | None = None, limit: int = 50) -> tuple[str, str]:
    today = today or date.today()
    q = " " + re.sub(r"[?!.,;:\"“”]+", " ", question.lower()) + " "
    q = re.sub(r"\s+", " ", q)
    notes: list[str] = []

    # --- period
    found = find_period_in_text(q, today)
    period: Period | None = None
    if found:
        period, phrase = found
        q = q.replace(f" {phrase} ", " ")
        notes.append(f"period: {period.label}")

    # --- direction
    direction = "credit" if re.search(r"\b(income|earn(ed|ings)?|received|salary|refunds?|cashback|credited|got paid)\b", q) else "debit"

    # --- category (aliases and names)
    category: str | None = None
    for key in _ALIAS_KEYS:
        if f" {key} " in q:
            category = ALIASES.get(key) or next(n for n in CATEGORY_NAMES if n.lower() == key)
            q = q.replace(f" {key} ", " ")
            break

    # --- merchant (explicit keyword, or "at/from <word>")
    merchant: str | None = None
    for kw in _MERCHANT_KEYWORDS:
        if f" {kw} " in q:
            merchant = kw
            q = q.replace(f" {kw} ", " ")
            break
    if merchant is None:
        m = re.search(r"\b(?:at|from|on|to|with)\s+([a-z][a-z0-9&'.\-]{2,})\b", q)
        if m and m.group(1) not in _STOP and m.group(1) not in _ALIAS_KEYS:
            merchant = m.group(1)

    # --- amount thresholds
    min_amount = max_amount = None
    m = re.search(r"\b(?:over|above|more than|greater than|at least|>=?|bigger than|exceeding)\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?k?)\b", q)
    if m:
        min_amount = _parse_amount(m.group(1))
    m = re.search(r"\b(?:under|below|less than|smaller than|at most|<=?|up to)\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?k?)\b", q)
    if m:
        max_amount = _parse_amount(m.group(1))

    # --- top N
    n = 5
    m = re.search(r"\btop\s+(\d+)\b", q)
    if m:
        n = int(m.group(1))

    # --- intent
    wants_merchants = re.search(r"\b(merchants?|places?|vendors?|stores?|shops?|where)\b", q) is not None
    wants_categories = re.search(r"\b(categor(y|ies)|breakdown|split)\b", q) is not None
    by_month = re.search(r"\b(by month|per month|monthly|each month|month by month|trend)\b", q) is not None
    by_day = re.search(r"\b(by day|per day|daily|each day)\b", q) is not None
    by_week = re.search(r"\b(by week|per week|weekly|each week)\b", q) is not None
    is_count = re.search(r"\b(how many|count|number of)\b", q) is not None
    is_avg = re.search(r"\b(average|avg|mean|typical)\b", q) is not None
    is_sum = re.search(r"\b(how much|total|sum|spend|spent|spending|expenses?|cost)\b", q) is not None
    is_largest = re.search(r"\b(largest|biggest|most expensive|highest|top)\b", q) is not None and not (wants_merchants or wants_categories)
    is_list = re.search(r"\b(list|show|find|which|what|all|every|recent|latest|last few)\b", q) is not None

    where: list[str] = [f"direction = '{direction}'"]
    if category:
        where.append(f"lower(category) = lower('{category.replace(chr(39), chr(39) * 2)}')")
        notes.append(f"category: {category}")
    elif direction == "debit":
        where.append("COALESCE(category_kind, 'expense') <> 'transfer'")
    if merchant:
        where.append(f"merchant ILIKE '%{merchant.replace(chr(39), chr(39) * 2)}%'")
        notes.append(f"merchant contains '{merchant}'")
    if min_amount is not None:
        where.append(f"amount >= {min_amount:g}")
        notes.append(f"amount >= {min_amount:g}")
    if max_amount is not None:
        where.append(f"amount <= {max_amount:g}")
        notes.append(f"amount <= {max_amount:g}")

    aggregate = is_sum or is_count or is_avg or wants_merchants or wants_categories or by_month or by_day or by_week
    if period is None and aggregate and not (by_month or by_week):
        period = resolve_period("this month", today)
        notes.append(f"period assumed: {period.label}")
    if period is None and (by_month or by_week):
        period = resolve_period("last 6 months", today)
        notes.append(f"period assumed: {period.label}")
    if period is not None:
        where.append(f"date BETWEEN '{period.start.isoformat()}' AND '{period.end.isoformat()}'")
    clause = " AND ".join(where)
    what = "income" if direction == "credit" else "spending"

    if by_month or by_day or by_week:
        fmt = "YYYY-MM" if by_month else 'IYYY-"W"IW' if by_week else "YYYY-MM-DD"
        col = "month" if by_month else "week" if by_week else "day"
        sql = (f"SELECT to_char(date, '{fmt}') AS {col}, {_money('SUM(amount)')} AS total, COUNT(*) AS transactions "
               f"FROM v_transactions WHERE {clause} GROUP BY 1 ORDER BY 1")
        return sql, f"{what} by {col}; " + "; ".join(notes)
    if wants_merchants:
        sql = (f"SELECT merchant, {_money('SUM(amount)')} AS total, COUNT(*) AS transactions, MAX(category) AS category "
               f"FROM v_transactions WHERE {clause} GROUP BY merchant ORDER BY total DESC LIMIT {n}")
        return sql, f"top {n} merchants by {what}; " + "; ".join(notes)
    if wants_categories:
        sql = (f"SELECT COALESCE(category, 'Uncategorized') AS category, {_money('SUM(amount)')} AS total, COUNT(*) AS transactions "
               f"FROM v_transactions WHERE {clause} GROUP BY category_id, category ORDER BY total DESC LIMIT {max(n, 20)}")
        return sql, f"{what} by category; " + "; ".join(notes)
    if is_count and not is_largest:
        return f"SELECT COUNT(*) AS transactions, {_money('SUM(amount)')} AS total FROM v_transactions WHERE {clause}", \
            f"count of {what} transactions; " + "; ".join(notes)
    if is_avg:
        return (f"SELECT {_money('AVG(amount)')} AS average_amount, COUNT(*) AS transactions, {_money('SUM(amount)')} AS total "
                f"FROM v_transactions WHERE {clause}"), f"average {what} per transaction; " + "; ".join(notes)
    if is_largest:
        n_rows = n if re.search(r"\btop\s+\d+\b", q) else (n if re.search(r"\b(purchases|transactions|expenses)\b", q) else 1)
        return (f"SELECT id, date, merchant, amount, category, description FROM v_transactions WHERE {clause} "
                f"ORDER BY amount DESC LIMIT {n_rows}"), f"largest {what} transactions; " + "; ".join(notes)
    if is_sum and not is_list:
        return (f"SELECT {_money('SUM(amount)')} AS total, COUNT(*) AS transactions, {_money('AVG(amount)')} AS average "
                f"FROM v_transactions WHERE {clause}"), f"total {what}; " + "; ".join(notes)
    if is_list or category or merchant or min_amount is not None or max_amount is not None:
        return (f"SELECT id, date, merchant, amount, direction, category, description FROM v_transactions WHERE {clause} "
                f"ORDER BY date DESC, id DESC LIMIT {limit}"), f"listing {what} transactions; " + "; ".join(notes)
    raise UnsupportedQuestion(
        "I could not turn that question into SQL without an LLM. Ask about totals, counts, top merchants or categories, "
        "largest purchases, or listings (for example: 'how much did I spend on food last month', 'top 5 merchants this "
        "month', 'transactions over 5000 in august'), or call run_sql / list_transactions directly."
    )
