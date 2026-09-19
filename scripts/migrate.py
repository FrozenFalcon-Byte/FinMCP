#!/usr/bin/env python3
"""Apply supabase/migrations/*.sql to the configured database (Supabase or local).

    python scripts/migrate.py            # uses SUPABASE_DB_URL / FINMCP_DATABASE_URL, else the embedded local cluster
    python scripts/migrate.py --url postgresql://...

Equivalent to `supabase db push` for people who have the Supabase CLI; this script needs only the Python venv."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finmcp.config import load_settings  # noqa: E402
from finmcp.db import database_for, open_database  # noqa: E402
from finmcp.db.database import redact_url  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="database URL (default: from the environment)")
    args = ap.parse_args()
    db = open_database(args.url, migrate=False) if args.url else database_for(load_settings(), migrate=False)
    applied = db.migrate()
    print(f"{redact_url(db.url)}: {'applied ' + ', '.join(applied) if applied else 'already up to date'} (rls: {db.rls})")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
