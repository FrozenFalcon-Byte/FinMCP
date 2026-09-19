"""Database layer: PostgreSQL (Supabase in production, an embedded cluster locally) with per-account RLS."""
from __future__ import annotations

from pathlib import Path

from ..config import ROOT, Settings
from .database import Database, open_database
from .events import LedgerEvents, events
from .repository import Category, Goal, Repository, Transaction, fingerprint_for, merchant_key


def database_for(settings: Settings, *, migrate: bool = True) -> Database:
    """Connect to the configured database, or start the embedded local cluster when none is configured."""
    url = settings.database_url
    if not url:
        from .devpg import dev_cluster

        cluster = dev_cluster(Path(ROOT), port=settings.pg_port)
        cluster.start()
        url = cluster.url
    return open_database(url, migrate=migrate)


__all__ = ["Category", "Database", "Goal", "LedgerEvents", "Repository", "Transaction", "database_for", "events",
           "fingerprint_for", "merchant_key", "open_database"]
