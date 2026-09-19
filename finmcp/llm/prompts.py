"""Prompt text shared by the LLM provider and the agent."""
from __future__ import annotations

from datetime import date

from ..taxonomy import DEFAULT_CATEGORIES

SCHEMA_DOC_TEMPLATE = """PostgreSQL database for personal finance (currency {currency}). Row Level Security already limits every
query to the current account, so never filter by user_id.

TABLE transactions
  id BIGINT PRIMARY KEY
  date DATE            -- compare with 'YYYY-MM-DD' literals
  amount NUMERIC       -- always >= 0; the sign is carried by `direction`
  direction TEXT       -- 'debit' = money out (spending), 'credit' = money in (income, refunds)
  currency TEXT
  merchant TEXT        -- normalised merchant / counterparty name, e.g. 'SWIGGY', 'UBER'
  description TEXT     -- bank narration, e.g. 'UPI/SWIGGY/4123.../Food order'
  category_id INTEGER  -- FK -> categories.id (NULL = uncategorized)
  category_confidence REAL, category_source TEXT ('user'|'memory'|'rule'|'llm'|'seed')
  source TEXT          -- 'manual'|'receipt'|'statement'|'sms'|'seed'|'api'
  client TEXT          -- which app wrote it: 'web', 'assistant', 'Claude Desktop', ...
  raw_text TEXT, needs_review BOOLEAN, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ

TABLE categories
  id BIGINT PRIMARY KEY, name TEXT, kind TEXT ('expense'|'income'|'transfer'),
  budget_limit NUMERIC -- monthly budget, NULL when none
  description TEXT

VIEW v_transactions  -- PREFER THIS VIEW: every transactions column plus `category` (name) and `category_kind`
VIEW monthly_summary(month 'YYYY-MM', category, category_kind, spent, received, n)

Conventions
- "Spend" / "expenses" = direction = 'debit' AND COALESCE(category_kind, 'expense') <> 'transfer'
  (transfers and investments move money; they are not consumption).
- "Income" = direction = 'credit'.
- Months: to_char(date, 'YYYY-MM') = 'YYYY-MM'. Days: to_char(date, 'YYYY-MM-DD'). Use date literals like DATE '2026-08-01'.
- Case-insensitive text: lower(category) = lower('Food & Dining'), merchant ILIKE '%swiggy%'.
- Category names (use exact spelling): {categories}
- Today is {today}. "This month" = {this_month}. "Last month" = {last_month}.
- Only SELECT statements. Always add a LIMIT (max 200) for row listings. Round money with ROUND(x::numeric, 2).
- GROUP BY must list every non-aggregated column (PostgreSQL).
"""


def schema_doc(currency: str = "INR", today: date | None = None) -> str:
    today = today or date.today()
    this_month = today.strftime("%Y-%m")
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return SCHEMA_DOC_TEMPLATE.format(
        currency=currency,
        categories=", ".join(c.name for c in DEFAULT_CATEGORIES),
        today=today.isoformat(),
        this_month=this_month,
        last_month=f"{y:04d}-{m:02d}",
    )


CATEGORIZE_SYSTEM = """You categorise personal-finance transactions for a user in India.
Pick exactly one category from the list provided. Use the merchant name, the bank narration and the amount.
Typical narrations: 'UPI/<merchant>/<ref>/<note>', 'POS <merchant>', 'NEFT/SALARY/...', 'ACH/<biller>'.
Person-to-person UPI transfers (P2P) are 'Transfers'. Salary, refunds, cashback and interest are 'Income'.
SIPs, mutual funds and brokerages are 'Investments'. Card bill payments are 'Transfers'.
Return a calibrated confidence: 0.9+ only when the merchant is unambiguous, 0.5-0.7 when you are guessing
from weak signals, and below 0.5 when nothing fits (then choose 'Other')."""

TEXT_TO_SQL_SYSTEM = """You translate a natural-language question about someone's personal finances into ONE PostgreSQL SELECT
statement over the schema below. Return the SQL and a one-sentence explanation of how you interpreted the question
(period, filters, what is being aggregated). Never modify data. Prefer v_transactions. Use ROUND for money.
If the question is ambiguous about the period, assume the current month and say so in the explanation.

{schema}"""


EXTRACT_RECEIPT_SYSTEM = """You read retail and restaurant receipts (often from India) and extract the purchase.
Return the merchant name as printed at the top, the date in ISO form if legible, the final amount actually paid
(after taxes and discounts; prefer 'Grand Total' / 'Net Payable' over subtotals), the payment method if shown,
and the individual line items with quantity, unit price and line total when they are readable.
Set confidence low when the image is blurry, cropped, or the total is ambiguous."""

EXTRACT_TRANSACTIONS_SYSTEM = """You extract financial transactions from messy text: bank SMS alerts, statement lines,
or pasted tables. For each real money movement return the ISO date, the positive amount, whether it is a debit
(money out: debited, spent, paid, sent, withdrawn) or credit (money in: credited, received, refund, cashback, salary),
the merchant / counterparty name, and a short description. Skip OTPs, promotions, payment requests, reminders,
balance-only alerts, and failed transactions. Use today's year when a message shows no year. Never invent rows."""
