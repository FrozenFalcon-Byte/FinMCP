"""PostgreSQL access: a connection pool, migrations, and per-account transactions.

`Database.tenant(user_id)` opens a transaction as the `authenticated` role with the account's JWT claims set, the
same way Supabase's PostgREST serves an API request. Row Level Security then limits every statement in that
transaction to the account's own rows. The repository still adds explicit `user_id = %s` filters, so isolation
holds even on a server where the connecting role cannot switch to `authenticated`.
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql as psql
from psycopg.rows import dict_row
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from ..config import ROOT

log = logging.getLogger("finmcp.db")
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"


def _configure(conn: psycopg.Connection) -> None:
    conn.adapters.register_loader("numeric", FloatLoader)
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()


def redact_url(url: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


class Database:
    def __init__(self, url: str, *, min_size: int = 4, max_size: int = 12):
        self.url = url
        self.pool = ConnectionPool(
            url, min_size=min_size, max_size=max_size, open=True, configure=_configure, timeout=20,
            max_idle=3600, max_lifetime=4 * 3600,  # opening a connection to a far-away pooler costs seconds: keep them warm
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 15, "autocommit": True},
        )
        self.rls = "unknown"

    # ---------------------------------------------------------------- lifecycle

    def migrate(self, migrations_dir: Path | None = None) -> list[str]:
        """Apply every SQL file under supabase/migrations that has not been applied yet, in name order."""
        folder = Path(migrations_dir or MIGRATIONS_DIR)
        applied: list[str] = []
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            conn.execute("SELECT pg_advisory_xact_lock(7461)")  # one migrator at a time
            done = {r["version"] for r in conn.execute("SELECT version FROM public.schema_migrations").fetchall()}
            for path in sorted(folder.glob("*.sql")):
                if path.name in done:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO public.schema_migrations (version) VALUES (%s)", (path.name,))
                applied.append(path.name)
        self.rls = self._probe_rls()
        if applied:
            log.info("Applied migrations: %s", ", ".join(applied))
        log.info("Database %s ready (row level security: %s)", redact_url(self.url), self.rls)
        return applied

    def _probe_rls(self) -> str:
        try:
            with self.pool.connection() as conn, conn.transaction():
                conn.execute("SET LOCAL ROLE authenticated")
                conn.execute("SELECT set_config('request.jwt.claims', '{\"sub\":\"00000000-0000-0000-0000-000000000000\"}', true)")
                conn.execute("SELECT count(*) FROM public.transactions")
            return "enforced"
        except psycopg.Error as exc:
            log.warning("Cannot switch to the authenticated role (%s); relying on application-level scoping only.", str(exc).strip())
            return "app-scoped"

    def close(self) -> None:
        self.pool.close()

    # ---------------------------------------------------------------- connections

    @contextmanager
    def admin(self) -> Iterator[psycopg.Connection]:
        """A transaction as the connecting role (account tables, migrations, token lookups)."""
        with self.pool.connection() as conn, conn.transaction():
            yield conn

    @contextmanager
    def tenant(self, user_id: str, *, read_only: bool = False, timeout_ms: int | None = None) -> Iterator[psycopg.Connection]:
        """A transaction scoped to one account: RLS on, JWT claims set, optionally read-only with a statement timeout."""
        # Every setting goes in one statement: over a slow link (a hosted pooler far away) each round trip counts.
        # set_config(..., true) is the function form of SET LOCAL; 'role' is SET ROLE, 'transaction_read_only' is
        # SET TRANSACTION READ ONLY (valid here because it runs before any other query in the transaction).
        settings: list[tuple[str, str]] = []
        if read_only:
            settings.append(("transaction_read_only", "on"))
        if timeout_ms:
            settings.append(("statement_timeout", str(int(timeout_ms))))
        if self.rls == "enforced":
            settings.append(("role", "authenticated"))
        settings.append(("request.jwt.claims", json.dumps({"sub": user_id, "role": "authenticated"})))
        # BEGIN and the settings travel as one simple-protocol message (values rendered as SQL literals by psycopg), so
        # opening a scoped transaction costs one round trip instead of three. Connections run in autocommit mode,
        # which keeps psycopg from sending a BEGIN of its own; queries inside then behave exactly as usual.
        opener = psql.SQL("BEGIN; SELECT {}").format(psql.SQL(", ").join(
            psql.SQL("set_config({}, {}, true)").format(psql.Literal(k), psql.Literal(v)) for k, v in settings))
        with self.pool.connection() as conn:
            conn.execute(opener)
            try:
                yield conn
            except BaseException:
                with contextlib.suppress(psycopg.Error):
                    conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")


def open_database(url: str, *, migrate: bool = True, **pool_kwargs: int) -> Database:
    db = Database(url, **pool_kwargs)
    if migrate:
        db.migrate()
    else:
        db.rls = db._probe_rls()
    return db


__all__ = ["MIGRATIONS_DIR", "Database", "open_database", "redact_url"]
