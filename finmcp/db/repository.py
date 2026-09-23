"""Typed data access for one account's ledger. Every SQL statement the server runs lives here.

A `Repository` is bound to a user id and a client label (which MCP client is acting: 'web', 'assistant',
'Claude Desktop', ...). Every statement runs inside `Database.tenant(user_id)`, so Row Level Security applies,
and every write is stamped with the client and published on the change feed.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from .database import Database
from .events import events

# --------------------------------------------------------------------------- models


class Category(BaseModel):
    id: int
    name: str
    kind: str
    budget_limit: float | None = None
    description: str | None = None


class Transaction(BaseModel):
    id: int
    date: str
    amount: float
    direction: str
    currency: str
    merchant: str
    description: str | None = None
    category_id: int | None = None
    category: str | None = None
    category_kind: str | None = None
    category_confidence: float | None = None
    category_source: str | None = None
    source: str
    client: str | None = None
    raw_text: str | None = None
    fingerprint: str | None = None
    needs_review: bool = False
    created_at: str
    updated_at: str


class Goal(BaseModel):
    id: int
    name: str
    target: float
    saved: float
    due: str | None = None
    icon: str | None = None
    created_at: str
    updated_at: str


class Emi(BaseModel):
    id: int
    name: str
    lender: str | None = None
    amount: float
    start_date: str
    tenure_months: int
    principal: float | None = None
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- helpers

_MERCHANT_NOISE = re.compile(
    r"\b(upi|pos|imps|neft|rtgs|ach|bbps|ref|txn|payment|paid|to|via|ltd|pvt|private|limited|india|ind|ecom|online|p2a|p2p"
    r"|com|in|www|order|orders|bill|bills|trip|purchase|membership|services|service|technologies|tech|enterprises|retail"
    r"|store|stores|shop|merchant|qr|x{2,})\b"
)


def merchant_key(merchant: str) -> str:
    """Normalise a merchant string so 'SWIGGY*ORDER 8812' and 'Swiggy' share a key."""
    s = merchant.lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    s = _MERCHANT_NOISE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:60]


def _same_merchant(a: str, b: str) -> bool:
    """'Company' and 'Company Ltd' are the same counterparty; 'Swiggy' and 'Swiggy Instamart' are close enough."""
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def fingerprint_for(date: str, amount: float, direction: str, merchant: str, raw_text: str | None = None) -> str:
    basis = "|".join([date, f"{float(amount):.2f}", direction, merchant_key(merchant), (raw_text or "").strip().lower()[:120]])
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def jsonable(value: Any) -> Any:
    """Postgres values -> what JSON (and the old SQLite-era callers) expect."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def clean_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: jsonable(v) for k, v in row.items()}


_ORDER_WHITELIST = {
    "date_desc": "date DESC, id DESC",
    "date_asc": "date ASC, id ASC",
    "amount_desc": "amount DESC, id DESC",
    "amount_asc": "amount ASC, id ASC",
}

_BUCKETS = {"day": "YYYY-MM-DD", "month": "YYYY-MM", "week": 'IYYY-"W"IW'}

# Functions that could change session state, block, or read outside the ledger from inside a SELECT. The read-only
# transaction and the `authenticated` role already stop most of them; the denylist keeps set_config (which could
# rewrite the RLS claims mid-statement) and friends out regardless.
_DENIED_FUNCTIONS = re.compile(
    r"\b(set_config|current_setting|pg_sleep\w*|pg_read_\w+|pg_ls_\w+|pg_stat_file|lo_\w+|dblink\w*|pg_terminate_backend|"
    r"pg_cancel_backend|pg_notify|pg_advisory_\w+|pg_try_advisory_\w+|pg_reload_conf|pg_rotate_logfile|txid_\w+|pg_export_snapshot)\b",
    re.IGNORECASE,
)

TRANSACTION_FIELDS = (
    "date", "amount", "direction", "currency", "merchant", "description", "category_id",
    "category_confidence", "category_source", "source", "raw_text", "fingerprint", "needs_review",
)

TX_COLUMNS = ("id, date, amount, direction, currency, merchant, description, category_id, category, category_kind, "
              "category_confidence, category_source, source, client, raw_text, fingerprint, needs_review, created_at, updated_at")


class Repository:
    """All reads and writes for one account, as one client."""

    def __init__(self, db: Database, user_id: str, *, client: str = "app"):
        self.db = db
        self.user_id = str(user_id)
        self.client = client

    # ---------------------------------------------------------------- plumbing

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.db.tenant(self.user_id) as conn:
            return clean_row(conn.execute(sql, params).fetchone())

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.db.tenant(self.user_id) as conn:
            return [clean_row(r) for r in conn.execute(sql, params).fetchall()]  # type: ignore[misc]

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.db.tenant(self.user_id) as conn:
            return conn.execute(sql, params).rowcount

    def _emit(self, entity: str, action: str, entity_id: int | None = None, **extra: Any) -> None:
        events.emit(self.user_id, type="write", entity=entity, action=action, id=entity_id, client=self.client, **extra)

    # ---------------------------------------------------------------- categories

    def list_categories(self) -> list[Category]:
        rows = self._all("SELECT id, name, kind, budget_limit, description FROM categories WHERE user_id = %s ORDER BY kind, name", (self.user_id,))
        return [Category(**r) for r in rows]

    def get_category(self, ref: int | str) -> Category | None:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            row = self._one("SELECT id, name, kind, budget_limit, description FROM categories WHERE user_id = %s AND id = %s", (self.user_id, int(ref)))
        else:
            row = self._one("SELECT id, name, kind, budget_limit, description FROM categories WHERE user_id = %s AND lower(name) = lower(%s)",
                            (self.user_id, ref.strip()))
        return Category(**row) if row else None

    def upsert_category(self, name: str, kind: str = "expense", budget_limit: float | None = None, description: str | None = None) -> Category:
        row = self._one(
            """INSERT INTO categories (user_id, name, kind, budget_limit, description) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (user_id, lower(name)) DO UPDATE SET kind = EXCLUDED.kind,
                 budget_limit = COALESCE(EXCLUDED.budget_limit, categories.budget_limit),
                 description = COALESCE(EXCLUDED.description, categories.description)
               RETURNING id, name, kind, budget_limit, description""",
            (self.user_id, name.strip(), kind, budget_limit, description),
        )
        assert row is not None
        return Category(**row)

    def set_budget(self, name: str, monthly_limit: float | None) -> Category:
        cat = self.get_category(name)
        if cat is None:
            raise ValueError(f"Unknown category: {name!r}")
        self._exec("UPDATE categories SET budget_limit = %s WHERE user_id = %s AND id = %s", (monthly_limit, self.user_id, cat.id))
        self._emit("category", "budget", cat.id)
        return self.get_category(cat.id)  # type: ignore[return-value]

    # ---------------------------------------------------------------- transactions

    @staticmethod
    def _to_transaction(row: dict[str, Any]) -> Transaction:
        return Transaction(**row)

    def get_transaction(self, tx_id: int) -> Transaction | None:
        row = self._one(f"SELECT {TX_COLUMNS} FROM v_transactions WHERE user_id = %s AND id = %s", (self.user_id, tx_id))
        return self._to_transaction(row) if row else None

    def insert_transaction(
        self,
        *,
        date: str,
        amount: float,
        merchant: str,
        direction: str = "debit",
        currency: str = "INR",
        description: str | None = None,
        category_id: int | None = None,
        category_confidence: float | None = None,
        category_source: str | None = None,
        source: str = "manual",
        raw_text: str | None = None,
        fingerprint: str | None = None,
        needs_review: bool = False,
        ignore_duplicate: bool = False,
    ) -> Transaction | None:
        """Insert one transaction. With ignore_duplicate=True a fingerprint clash returns None."""
        conflict = "ON CONFLICT (user_id, fingerprint) WHERE fingerprint IS NOT NULL DO NOTHING" if ignore_duplicate else ""
        row = self._one(
            f"""INSERT INTO transactions (user_id, date, amount, direction, currency, merchant, description, category_id,
                  category_confidence, category_source, source, client, raw_text, fingerprint, needs_review)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) {conflict} RETURNING id""",
            (self.user_id, date, float(amount), direction, currency, merchant.strip(), description, category_id,
             category_confidence, category_source, source, self.client, raw_text, fingerprint, bool(needs_review)),
        )
        if row is None:
            return None
        tx = self.get_transaction(int(row["id"]))
        self._emit("transaction", "insert", int(row["id"]))
        return tx

    def insert_many(self, rows: list[dict[str, Any]]) -> int:
        """Insert many transactions in one transaction, pipelined (seeding, large imports). Rows whose fingerprint
        already exists are skipped. Returns how many were inserted."""
        if not rows:
            return 0
        sql = """INSERT INTO transactions (user_id, date, amount, direction, currency, merchant, description, category_id,
                   category_confidence, category_source, source, client, raw_text, fingerprint, needs_review)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                 ON CONFLICT (user_id, fingerprint) WHERE fingerprint IS NOT NULL DO NOTHING"""
        params = [(self.user_id, r["date"], float(r["amount"]), r.get("direction", "debit"), r.get("currency", "INR"), str(r["merchant"]).strip(),
                   r.get("description"), r.get("category_id"), r.get("category_confidence"), r.get("category_source"), r.get("source", "manual"),
                   self.client, r.get("raw_text"), r.get("fingerprint"), bool(r.get("needs_review", False))) for r in rows]
        count = "SELECT count(*) AS n FROM transactions WHERE user_id = %s"
        with self.db.tenant(self.user_id) as conn:
            before = int(conn.execute(count, (self.user_id,)).fetchone()["n"])  # type: ignore[index]
            with conn.cursor() as cur:
                cur.executemany(sql, params)  # psycopg pipelines executemany: a handful of round trips, not one per row
            inserted = int(conn.execute(count, (self.user_id,)).fetchone()["n"]) - before  # type: ignore[index]
        if inserted:
            self._emit("ledger", "bulk_insert", None, count=inserted)
        return inserted

    def update_transaction(self, tx_id: int, **fields: Any) -> Transaction:
        bad = set(fields) - set(TRANSACTION_FIELDS)
        if bad:
            raise ValueError(f"Cannot update fields: {sorted(bad)}")
        if not fields:
            tx = self.get_transaction(tx_id)
            if tx is None:
                raise ValueError(f"Transaction {tx_id} not found")
            return tx
        if "needs_review" in fields:
            fields["needs_review"] = bool(fields["needs_review"])
        if "amount" in fields:
            fields["amount"] = float(fields["amount"])
        sets = ", ".join(f"{k} = %s" for k in fields)
        n = self._exec(f"UPDATE transactions SET {sets} WHERE user_id = %s AND id = %s", (*fields.values(), self.user_id, tx_id))
        if n == 0:
            raise ValueError(f"Transaction {tx_id} not found")
        self._emit("transaction", "update", tx_id)
        return self.get_transaction(tx_id)  # type: ignore[return-value]

    def delete_transaction(self, tx_id: int) -> bool:
        n = self._exec("DELETE FROM transactions WHERE user_id = %s AND id = %s", (self.user_id, tx_id))
        if n:
            self._emit("transaction", "delete", tx_id)
        return n > 0

    def fingerprint_exists(self, fingerprint: str) -> bool:
        return self._one("SELECT 1 AS x FROM transactions WHERE user_id = %s AND fingerprint = %s LIMIT 1", (self.user_id, fingerprint)) is not None

    def count_transactions(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM transactions WHERE user_id = %s", (self.user_id,))
        return int(row["n"]) if row else 0

    def list_transactions(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        category: str | None = None,
        merchant: str | None = None,
        direction: str | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        uncategorized_only: bool = False,
        needs_review_only: bool = False,
        search: str | None = None,
        source: str | None = None,
        client: str | None = None,
        order: str = "date_desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        where: list[str] = ["user_id = %s"]
        params: list[Any] = [self.user_id]
        if start:
            where.append("date >= %s")
            params.append(start)
        if end:
            where.append("date <= %s")
            params.append(end)
        if category:
            where.append("lower(category) = lower(%s)")
            params.append(category.strip())
        if merchant:
            where.append("merchant ILIKE %s")
            params.append(f"%{merchant.strip()}%")
        if direction:
            where.append("direction = %s")
            params.append(direction)
        if min_amount is not None:
            where.append("amount >= %s")
            params.append(float(min_amount))
        if max_amount is not None:
            where.append("amount <= %s")
            params.append(float(max_amount))
        if uncategorized_only:
            where.append("category_id IS NULL")
        if needs_review_only:
            where.append("needs_review")
        if source:
            where.append("source = %s")
            params.append(source)
        if client:
            where.append("client = %s")
            params.append(client)
        if search:
            where.append("(merchant ILIKE %s OR description ILIKE %s OR raw_text ILIKE %s)")
            params.extend([f"%{search}%"] * 3)
        clause = "WHERE " + " AND ".join(where)
        order_sql = _ORDER_WHITELIST.get(order, _ORDER_WHITELIST["date_desc"])
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self.db.tenant(self.user_id) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) AS n FROM v_transactions {clause}", params).fetchone()["n"])  # type: ignore[index]
            rows = conn.execute(f"SELECT {TX_COLUMNS} FROM v_transactions {clause} ORDER BY {order_sql} LIMIT %s OFFSET %s",
                                (*params, limit, offset)).fetchall()
        return [self._to_transaction(clean_row(r)) for r in rows], total  # type: ignore[arg-type]

    def uncategorized_ids(self, limit: int = 100) -> list[int]:
        rows = self._all("SELECT id FROM transactions WHERE user_id = %s AND category_id IS NULL ORDER BY date DESC, id DESC LIMIT %s",
                         (self.user_id, limit))
        return [int(r["id"]) for r in rows]

    # ---------------------------------------------------------------- guarded SQL

    def select(self, sql: str, params: Sequence[Any] = (), limit: int = 200) -> tuple[list[str], list[list[Any]], bool]:
        """Run a read-only SELECT inside a read-only, RLS-scoped transaction with a statement timeout."""
        stmt = sql.strip().rstrip(";").strip()
        if not stmt:
            raise ValueError("Empty SQL statement.")
        if ";" in stmt:
            raise ValueError("Only a single statement is allowed.")
        if not re.match(r"^(select|with)\b", stmt, re.IGNORECASE):
            raise ValueError("Only SELECT (or WITH ... SELECT) statements are allowed.")
        bad = _DENIED_FUNCTIONS.search(stmt)
        if bad:
            raise ValueError(f"Query rejected: {bad.group(1)}() is not allowed here.")
        limit = max(1, min(int(limit), 1000))
        wrapped = f"SELECT * FROM ({stmt}) AS q LIMIT {limit + 1}"
        try:
            with self.db.tenant(self.user_id, read_only=True, timeout_ms=5000) as conn:
                cur = conn.execute(wrapped, tuple(params) if params else None)
                fetched = cur.fetchall()
                cols = [d.name for d in cur.description or []]
                rows = [[jsonable(v) for v in r.values()] for r in fetched]
        except psycopg.Error as exc:
            raise ValueError(f"Query rejected: {str(exc).strip().splitlines()[0]}") from exc
        truncated = len(rows) > limit
        return cols, rows[:limit], truncated

    # ---------------------------------------------------------------- aggregates

    def totals(self, start: str, end: str) -> dict[str, Any]:
        row = self._one(
            """SELECT
                 COALESCE(SUM(CASE WHEN direction = 'debit' AND COALESCE(category_kind, 'expense') <> 'transfer' THEN amount END), 0) AS spent,
                 COALESCE(SUM(CASE WHEN direction = 'debit' AND category_kind = 'transfer' THEN amount END), 0) AS transfers_out,
                 COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount END), 0) AS received,
                 COUNT(*) AS n,
                 COALESCE(SUM(CASE WHEN category_id IS NULL THEN 1 ELSE 0 END), 0) AS uncategorized
               FROM v_transactions WHERE user_id = %s AND date BETWEEN %s AND %s""",
            (self.user_id, start, end),
        )
        return row or {"spent": 0, "transfers_out": 0, "received": 0, "n": 0, "uncategorized": 0}

    def spend_by_category(self, start: str, end: str, direction: str = "debit") -> list[dict[str, Any]]:
        return self._all(
            """SELECT COALESCE(category, 'Uncategorized') AS category, category_id,
                      COALESCE(category_kind, 'expense') AS kind,
                      SUM(amount) AS total, COUNT(*) AS n, MAX(amount) AS largest
               FROM v_transactions WHERE user_id = %s AND date BETWEEN %s AND %s AND direction = %s
               GROUP BY category_id, category, category_kind ORDER BY total DESC""",
            (self.user_id, start, end, direction),
        )

    def top_merchants(self, start: str, end: str, n: int = 10, direction: str = "debit") -> list[dict[str, Any]]:
        return self._all(
            """SELECT merchant, SUM(amount) AS total, COUNT(*) AS n, MAX(category) AS category
               FROM v_transactions WHERE user_id = %s AND date BETWEEN %s AND %s AND direction = %s
               GROUP BY merchant ORDER BY total DESC LIMIT %s""",
            (self.user_id, start, end, direction, n),
        )

    def series(self, start: str, end: str, bucket: str = "day", direction: str = "debit") -> list[dict[str, Any]]:
        fmt = _BUCKETS.get(bucket, _BUCKETS["day"])
        return self._all(
            f"""SELECT to_char(date, '{fmt}') AS bucket, SUM(amount) AS total, COUNT(*) AS n
                FROM v_transactions WHERE user_id = %s AND date BETWEEN %s AND %s AND direction = %s
                AND COALESCE(category_kind, 'expense') <> 'transfer'
                GROUP BY 1 ORDER BY 1""",
            (self.user_id, start, end, direction),
        )

    def monthly_by_category(self, months: int = 6) -> list[dict[str, Any]]:
        return self._all(
            """SELECT month, category, category_kind, spent, received, n FROM monthly_summary
               WHERE user_id = %s AND month >= (
                 SELECT to_char(MAX(date) - make_interval(months => %s), 'YYYY-MM') FROM transactions WHERE user_id = %s)
               ORDER BY month, spent DESC""",
            (self.user_id, max(0, months - 1), self.user_id),
        )

    def monthly_rollup(self, since_month: str) -> list[dict[str, Any]]:
        """Every month from `since_month` (YYYY-MM) onward, one row per category.

        `monthly_by_category` anchors on the last transaction, which is what a categoriser wants; a report is read
        against the calendar the person is living in, so this one anchors on a month the caller names."""
        return self._all(
            """SELECT month, category, category_kind, spent, received, n FROM monthly_summary
               WHERE user_id = %s AND month >= %s ORDER BY month, spent DESC""",
            (self.user_id, since_month),
        )

    def date_bounds(self) -> tuple[str | None, str | None]:
        row = self._one("SELECT MIN(date) AS first, MAX(date) AS last FROM transactions WHERE user_id = %s", (self.user_id,))
        return (row["first"], row["last"]) if row else (None, None)

    def debit_history(self, days: int = 400) -> list[dict[str, Any]]:
        """Debits over the last `days`, oldest first, for recurring-payment detection."""
        return self._all(
            """SELECT id, date, amount, merchant, category, category_kind FROM v_transactions
               WHERE user_id = %s AND direction = 'debit' AND date >= CURRENT_DATE - make_interval(days => %s)
               ORDER BY date ASC, id ASC""",
            (self.user_id, days),
        )

    # ------------------------------------------------------------------ autopay

    def list_autopay(self) -> list[dict[str, Any]]:
        return self._all(
            """SELECT id, merchant_key, merchant, amount::float AS amount, cadence, cadence_days, category,
                      next_due, active, posted_count, last_posted_on, created_at
               FROM autopay WHERE user_id = %s ORDER BY next_due ASC, merchant ASC""",
            (self.user_id,),
        )

    def get_autopay(self, merchant_key_: str) -> dict[str, Any] | None:
        return self._one(
            """SELECT id, merchant_key, merchant, amount::float AS amount, cadence, cadence_days, category,
                      next_due, active, posted_count, last_posted_on
               FROM autopay WHERE user_id = %s AND merchant_key = %s""",
            (self.user_id, merchant_key_),
        )

    def upsert_autopay(self, *, merchant: str, amount: float, cadence: str, cadence_days: int,
                       next_due: str, category: str | None = None, active: bool = True) -> dict[str, Any]:
        """One standing instruction per merchant. Turning an existing one back on keeps its history."""
        key = merchant_key(merchant)
        self._exec(
            """INSERT INTO autopay (user_id, merchant_key, merchant, amount, cadence, cadence_days, category, next_due, active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (user_id, merchant_key) DO UPDATE
                 SET merchant = EXCLUDED.merchant, amount = EXCLUDED.amount, cadence = EXCLUDED.cadence,
                     cadence_days = EXCLUDED.cadence_days, category = EXCLUDED.category,
                     next_due = EXCLUDED.next_due, active = EXCLUDED.active""",
            (self.user_id, key, merchant.strip(), float(amount), cadence, int(cadence_days), category, next_due, bool(active)),
        )
        self._emit("autopay", "upsert", None)
        row = self.get_autopay(key)
        assert row is not None
        return row

    def set_autopay_active(self, merchant: str, active: bool) -> dict[str, Any] | None:
        key = merchant_key(merchant)
        if self._exec("UPDATE autopay SET active = %s WHERE user_id = %s AND merchant_key = %s", (bool(active), self.user_id, key)):
            self._emit("autopay", "update", None)
        return self.get_autopay(key)

    def delete_autopay(self, merchant: str) -> bool:
        gone = self._exec("DELETE FROM autopay WHERE user_id = %s AND merchant_key = %s", (self.user_id, merchant_key(merchant))) > 0
        if gone:
            self._emit("autopay", "delete", None)
        return gone

    def due_autopay(self, on: str) -> list[dict[str, Any]]:
        return self._all(
            """SELECT id, merchant_key, merchant, amount::float AS amount, cadence, cadence_days, category, next_due, posted_count
               FROM autopay WHERE user_id = %s AND active AND next_due <= %s ORDER BY next_due ASC""",
            (self.user_id, on),
        )

    def advance_autopay(self, autopay_id: int, *, next_due: str, posted_on: str | None) -> None:
        """Move a rule to its next cycle. `posted_on` is None when the entry was already in the ledger."""
        if posted_on is None:
            self._exec("UPDATE autopay SET next_due = %s WHERE user_id = %s AND id = %s", (next_due, self.user_id, autopay_id))
            return
        self._exec(
            "UPDATE autopay SET next_due = %s, last_posted_on = %s, posted_count = posted_count + 1 WHERE user_id = %s AND id = %s",
            (next_due, posted_on, self.user_id, autopay_id),
        )

    def merchant_history(self, merchant: str, limit: int = 60) -> list[dict[str, Any]]:
        """Recent entries whose merchant reads like this one, newest first.

        This account's own record of whether money at that name goes out or comes in. The key normalises
        'SWIGGY*ORDER 8812' and 'Swiggy' onto one name, so the first word narrows the scan and the key decides."""
        key = merchant_key(merchant)
        if not key:
            return []
        rows = self._all(
            "SELECT merchant, direction FROM v_transactions WHERE user_id = %s AND merchant ILIKE %s ORDER BY date DESC LIMIT %s",
            (self.user_id, f"%{key.split(' ')[0]}%", max(1, min(int(limit), 200))),
        )
        return [r for r in rows if _same_merchant(key, merchant_key(str(r["merchant"])))]

    def account_plan(self) -> dict[str, Any]:
        """What the person said they take home and how much of it they mean to keep, from first-run setup.

        Read through the tenant connection, so it is the caller's own row or nothing."""
        row = self._one("SELECT monthly_income, keep_pct FROM profiles WHERE id = %s", (self.user_id,)) or {}
        income = row.get("monthly_income")
        return {"monthly_income": float(income) if income else None, "keep_pct": int(row["keep_pct"]) if row.get("keep_pct") is not None else None}

    # ---------------------------------------------------------------- merchant memory

    def recall_merchant(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        return self._one(
            """SELECT m.merchant_key, m.category_id, c.name AS category, m.hits, m.last_seen
               FROM merchant_memory m JOIN categories c ON c.id = m.category_id
               WHERE m.user_id = %s AND m.merchant_key = %s""",
            (self.user_id, key),
        )

    def remember_merchant(self, key: str, category_id: int) -> None:
        if not key:
            return
        self._exec(
            """INSERT INTO merchant_memory (user_id, merchant_key, category_id, hits, last_seen) VALUES (%s, %s, %s, 1, now())
               ON CONFLICT (user_id, merchant_key) DO UPDATE SET
                 hits = CASE WHEN merchant_memory.category_id = EXCLUDED.category_id THEN merchant_memory.hits + 1 ELSE 1 END,
                 category_id = EXCLUDED.category_id, last_seen = now()""",
            (self.user_id, key, category_id),
        )

    def forget_merchant(self, key: str) -> None:
        self._exec("DELETE FROM merchant_memory WHERE user_id = %s AND merchant_key = %s", (self.user_id, key))

    def merchant_memory_size(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM merchant_memory WHERE user_id = %s", (self.user_id,))
        return int(row["n"]) if row else 0

    def memory_examples(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._all(
            """SELECT m.merchant_key AS merchant, c.name AS category FROM merchant_memory m JOIN categories c ON c.id = m.category_id
               WHERE m.user_id = %s ORDER BY m.hits DESC, m.last_seen DESC LIMIT %s""",
            (self.user_id, limit),
        )

    # ---------------------------------------------------------------- goals

    def list_goals(self) -> list[Goal]:
        rows = self._all("SELECT id, name, target, saved, due, icon, created_at, updated_at FROM goals WHERE user_id = %s ORDER BY due NULLS LAST, id",
                         (self.user_id,))
        return [Goal(**r) for r in rows]

    def get_goal(self, goal_id: int) -> Goal | None:
        row = self._one("SELECT id, name, target, saved, due, icon, created_at, updated_at FROM goals WHERE user_id = %s AND id = %s",
                        (self.user_id, goal_id))
        return Goal(**row) if row else None

    def create_goal(self, name: str, target: float, *, saved: float = 0, due: str | None = None, icon: str | None = None) -> Goal:
        row = self._one(
            """INSERT INTO goals (user_id, name, target, saved, due, icon) VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, name, target, saved, due, icon, created_at, updated_at""",
            (self.user_id, name.strip(), float(target), float(saved), due, icon),
        )
        assert row is not None
        self._emit("goal", "insert", int(row["id"]))
        return Goal(**row)

    def update_goal(self, goal_id: int, **fields: Any) -> Goal:
        allowed = {"name", "target", "saved", "due", "icon"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Cannot update goal fields: {sorted(bad)}")
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            n = self._exec(f"UPDATE goals SET {sets} WHERE user_id = %s AND id = %s", (*fields.values(), self.user_id, goal_id))
            if n == 0:
                raise ValueError(f"Goal {goal_id} not found")
            self._emit("goal", "update", goal_id)
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Goal {goal_id} not found")
        return goal

    def delete_goal(self, goal_id: int) -> bool:
        n = self._exec("DELETE FROM goals WHERE user_id = %s AND id = %s", (self.user_id, goal_id))
        if n:
            self._emit("goal", "delete", goal_id)
        return n > 0

    # ---------------------------------------------------------------- EMIs

    def list_emis(self) -> list[Emi]:
        rows = self._all("SELECT id, name, lender, amount, start_date, tenure_months, principal, created_at, updated_at FROM emis WHERE user_id = %s ORDER BY start_date, id", (self.user_id,))
        return [Emi(**r) for r in rows]

    def get_emi(self, emi_id: int) -> Emi | None:
        row = self._one("SELECT id, name, lender, amount, start_date, tenure_months, principal, created_at, updated_at FROM emis WHERE user_id = %s AND id = %s", (self.user_id, emi_id))
        return Emi(**row) if row else None

    def create_emi(self, name: str, amount: float, start_date: str, tenure_months: int, *, lender: str | None = None,
                   principal: float | None = None) -> Emi:
        row = self._one(
            """INSERT INTO emis (user_id, name, lender, amount, start_date, tenure_months, principal) VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id, name, lender, amount, start_date, tenure_months, principal, created_at, updated_at""",
            (self.user_id, name.strip(), (lender or "").strip() or None, float(amount), start_date, int(tenure_months), principal),
        )
        assert row is not None
        self._emit("emi", "insert", int(row["id"]))
        return Emi(**row)

    def update_emi(self, emi_id: int, **fields: Any) -> Emi:
        bad = set(fields) - {"name", "lender", "amount", "start_date", "tenure_months", "principal"}
        if bad:
            raise ValueError(f"Cannot update EMI fields: {sorted(bad)}")
        if fields:
            sets = ", ".join(f"{k} = %s" for k in fields)
            if self._exec(f"UPDATE emis SET {sets} WHERE user_id = %s AND id = %s", (*fields.values(), self.user_id, emi_id)) == 0:
                raise ValueError(f"EMI {emi_id} not found")
            self._emit("emi", "update", emi_id)
        emi = self.get_emi(emi_id)
        if emi is None:
            raise ValueError(f"EMI {emi_id} not found")
        return emi

    def delete_emi(self, emi_id: int) -> bool:
        n = self._exec("DELETE FROM emis WHERE user_id = %s AND id = %s", (self.user_id, emi_id))
        if n:
            self._emit("emi", "delete", emi_id)
        return n > 0

    # ---------------------------------------------------------------- audit / imports / activity

    def audit(self, actor: str, action: str, entity: str | None = None, entity_id: int | None = None, detail: Any = None) -> None:
        self._exec(
            "INSERT INTO audit_log (user_id, actor, client, action, entity, entity_id, detail) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (self.user_id, actor, self.client, action, entity, entity_id, Jsonb(jsonable(detail)) if detail is not None else None),
        )

    def recent_audit(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._all("SELECT id, ts, actor, client, action, entity, entity_id, detail FROM audit_log WHERE user_id = %s ORDER BY id DESC LIMIT %s OFFSET %s",
                         (self.user_id, limit, offset))

    def clients_seen(self, limit: int = 20) -> list[dict[str, Any]]:
        """Which clients have written to this ledger, with counts and last activity."""
        return self._all(
            """SELECT COALESCE(client, 'unknown') AS client, COUNT(*) AS actions, MAX(ts) AS last_seen, MIN(ts) AS first_seen
               FROM audit_log WHERE user_id = %s GROUP BY 1 ORDER BY last_seen DESC LIMIT %s""",
            (self.user_id, limit),
        )

    def record_import(self, source_kind: str, source_name: str | None, parsed: int, inserted: int, duplicates: int, detail: Any = None) -> int:
        row = self._one(
            """INSERT INTO imports (user_id, source_kind, source_name, parsed, inserted, duplicates, detail) VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (self.user_id, source_kind, source_name, parsed, inserted, duplicates, Jsonb(jsonable(detail)) if detail is not None else None),
        )
        assert row is not None
        self._emit("import", "insert", int(row["id"]))
        return int(row["id"])

    def recent_imports(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._all("SELECT id, ts, source_kind, source_name, parsed, inserted, duplicates, detail FROM imports WHERE user_id = %s ORDER BY id DESC LIMIT %s",
                         (self.user_id, limit))

    # ---------------------------------------------------------------- account

    def erase_ledger(self) -> dict[str, int]:
        """Delete every row this account owns (all ledger tables). Used by 'delete my data'."""
        counts: dict[str, int] = {}
        with self.db.tenant(self.user_id) as conn:
            for table in ("audit_log", "imports", "goals", "emis", "merchant_memory", "transactions", "categories"):
                counts[table] = conn.execute(f"DELETE FROM {table} WHERE user_id = %s", (self.user_id,)).rowcount
        self._emit("ledger", "erase")
        return counts

    def close(self) -> None:  # kept for API compatibility; the pool is owned by Database
        return None
