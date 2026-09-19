#!/usr/bin/env python3
"""Register FinMCP in Claude Desktop's MCP config.

    python scripts/install_claude_desktop.py --token fm_...      # write (a .bak copy is kept)
    python scripts/install_claude_desktop.py --token fm_... --print
    python scripts/install_claude_desktop.py --remove

Create the token under Connect in the FinMCP app. Two ways to connect:
  remote (default): Claude Desktop runs `npx mcp-remote <API>/mcp` with the token as a bearer header. Works
                    wherever the API runs (your laptop, a server) and needs no Python on the machine.
  --stdio:          Claude Desktop launches this repo's venv Python with `-m finmcp --token ...` directly.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def remote_entry(api_url: str, token: str) -> dict:
    return {"command": "npx", "args": ["-y", "mcp-remote", f"{api_url.rstrip('/')}/mcp", "--header", f"Authorization: Bearer {token}"]}


def stdio_entry(token: str) -> dict:
    return {"command": str(VENV_PY), "args": ["-m", "finmcp", "--token", token, "--client", "Claude Desktop"], "env": {"PYTHONPATH": str(ROOT)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", default=os.environ.get("FINMCP_MCP_TOKEN"), help="personal MCP token from the app (fm_...)")
    ap.add_argument("--api-url", default=os.environ.get("FINMCP_PUBLIC_URL", "http://127.0.0.1:8000"), help="where the FinMCP API runs")
    ap.add_argument("--stdio", action="store_true", help="launch the server as a local process instead of mcp-remote")
    ap.add_argument("--print", action="store_true", help="print the snippet, do not write")
    ap.add_argument("--remove", action="store_true", help="remove the finmcp entry")
    args = ap.parse_args()

    if not args.remove and not args.token:
        print("Pass --token fm_... (create one under Connect in the FinMCP app).", file=sys.stderr)
        return 1
    if args.stdio and not VENV_PY.exists():
        print(f"virtualenv python not found at {VENV_PY}; create it with: python3 -m venv .venv && .venv/bin/pip install -e .", file=sys.stderr)
        return 1
    entry = stdio_entry(args.token) if args.stdio else remote_entry(args.api_url, args.token) if args.token else {}
    if args.print:
        print(json.dumps({"mcpServers": {"finmcp": entry}}, indent=2))
        return 0

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config: dict = {}
    if path.exists():
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError as exc:
            print(f"{path} is not valid JSON ({exc}); fix it by hand first.", file=sys.stderr)
            return 1
        shutil.copy2(path, path.with_suffix(".json.bak"))
    servers = config.setdefault("mcpServers", {})
    if args.remove:
        servers.pop("finmcp", None)
        print("removed finmcp from", path)
    else:
        servers["finmcp"] = entry
        print("registered finmcp in", path)
    path.write_text(json.dumps(config, indent=2) + "\n")
    print("Restart Claude Desktop, then look for the FinMCP tools under the connectors icon.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
