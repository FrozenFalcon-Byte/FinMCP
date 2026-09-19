#!/usr/bin/env python3
"""Manage the embedded local PostgreSQL used when no Supabase / FINMCP_DATABASE_URL is configured.

    python scripts/devpg.py start     # download (first time), init and start the cluster under data/
    python scripts/devpg.py stop
    python scripts/devpg.py status
    python scripts/devpg.py url       # print the connection URL
    python scripts/devpg.py psql      # open psql against it (uses the bundled binary if present)
    python scripts/devpg.py reset     # stop and delete the cluster (all local data!)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finmcp.config import load_settings  # noqa: E402
from finmcp.db.devpg import dev_cluster  # noqa: E402


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    settings = load_settings()
    cluster = dev_cluster(ROOT, port=settings.pg_port)
    if cmd == "start":
        cluster.start()
        print(f"running on {cluster.url}")
    elif cmd == "stop":
        cluster.stop()
        print("stopped")
    elif cmd == "status":
        print("running" if cluster.running() else "stopped", cluster.url)
    elif cmd == "url":
        print(cluster.url)
    elif cmd == "psql":
        binary = cluster.pg / "bin" / "psql"
        exe = str(binary) if binary.exists() else "psql"
        os.execvp(exe, [exe, cluster.url])
    elif cmd == "reset":
        if input("Delete the local cluster and ALL local data? [y/N] ").strip().lower() != "y":
            return 1
        cluster.destroy()
        print("deleted", cluster.data_dir)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.decode(errors="replace") if exc.stderr else exc, file=sys.stderr)
        sys.exit(1)
