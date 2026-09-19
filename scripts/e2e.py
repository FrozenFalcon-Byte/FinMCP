#!/usr/bin/env python3
"""End-to-end smoke test across every layer, on a throwaway embedded PostgreSQL cluster.

1. MCP server over stdio (subprocess, demo account): list tools, call a tool, read a resource, refuse a write.
2. Agent loop with the offline driver through the in-process connection.
3. FastAPI backend: anonymous refusal, registration, bearer auth, chat stream, SMS import, overview.
4. Remote MCP endpoint (/mcp) over real HTTP with a personal token: tool call, client attribution, isolation.

Exit code 0 means every layer answered correctly. Run: python scripts/e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="finmcp-e2e-"))

from finmcp.db.devpg import temp_cluster  # noqa: E402

CLUSTER = temp_cluster(ROOT, _TMP)
CLUSTER.start()
os.environ.update({
    "FINMCP_DATABASE_URL": CLUSTER.url, "FINMCP_DATA_DIR": str(_TMP / "data"), "FINMCP_LLM": "rules",
    "FINMCP_AGENT_DRIVER": "local", "FINMCP_JWT_SECRET": "e2e-secret-not-for-production-0123456789",
})
for var in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(var, None)

PY = ROOT / ".venv" / "bin" / "python"
FAILS: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        FAILS.append(label)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def stdio_layer() -> None:
    from agent import MCPConnection

    print("MCP server, stdio transport (demo account)")
    async with MCPConnection.stdio(args=("--seed-if-empty", "--llm", "rules", "--client", "e2e-stdio")) as conn:
        tools = await conn.list_tools()
        check(len(tools) >= 20, f"{len(tools)} tools listed")
        out = await conn.call_tool("get_summary", {"period": "last month"})
        check(out.ok and out.data["totals"]["spent"] > 0, "get_summary returns spend")
        status = await conn.read_resource_json("finmcp://status")
        check(status["transactions"] > 200 and status["rls"] == "enforced", f"status resource: {status['transactions']} transactions, rls {status['rls']}")
        out = await conn.call_tool("run_sql", {"sql": "DELETE FROM transactions"})
        check(not out.ok, "run_sql rejects writes")
        out = await conn.call_tool("list_recurring", {})
        check(out.ok and out.data["count"] >= 5, f"list_recurring found {out.data['count']} recurring payments")


async def agent_layer() -> None:
    from agent import Agent, LocalDriver, MCPConnection
    from finmcp.__main__ import resolve_principal
    from finmcp.config import load_settings
    from finmcp.db import database_for
    from finmcp.server import create_server, seed_account

    print("Agent loop (offline driver, in-process MCP)")
    settings = load_settings()
    db = database_for(settings)
    principal = resolve_principal(settings, db, token=None, email=None)
    server = create_server(settings, db=db, user_id=principal.user_id, client="e2e-agent")
    seed_account(server, only_if_empty=True)
    async with MCPConnection.in_process(server) as conn:
        agent = Agent(conn, LocalDriver())
        evs = [e async for e in agent.run("how much did I spend on groceries last month?")]
        kinds = [e["type"] for e in evs]
        check("tool_call" in kinds and kinds[-1] == "done", "tool call then done")
        check("| total |" in evs[-1]["text"], "rendered table in the answer")
    db.close()


def api_layer() -> tuple[str, str]:
    from fastapi.testclient import TestClient

    from api.main import create_app

    print("FastAPI backend")
    with TestClient(create_app()) as c:
        anon = c.get("/api/transactions")
        check(anon.status_code == 401, "ledger routes refuse anonymous requests")
        cfg = c.get("/api/auth/config").json()
        check(cfg["mode"] == "local", f"auth config: {cfg['mode']} mode")
        email = f"e2e-{os.getpid()}@example.com"
        r = c.post("/api/auth/register", json={"name": "E2E", "email": email, "password": "e2e-password", "sample_data": True})
        check(r.status_code == 201, f"registered {r.json().get('user', {}).get('email')}")
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        h = c.get("/api/health").json()
        check(h["ok"] and h["tools"] >= 20 and h["rls"] == "enforced", f"health: {h['tools']} tools, driver {h['driver']}, rls {h['rls']}")
        o = c.get("/api/overview").json()
        check(o["spent"] > 0 and o["safe_to_spend"]["per_day"] is not None, f"overview: spent {o['spent']:.0f}, safe/day {o['safe_to_spend']['per_day']}")
        with c.stream("POST", "/api/chat", json={"message": "which budgets am I about to blow?"}) as r:
            events = [json.loads(line) for line in r.iter_lines() if line]
        check(events[-1]["type"] == "done" and any(e["type"] == "tool_call" and e["name"] == "get_budget_summary" for e in events), "chat stream routed to get_budget_summary")
        with open(ROOT / "fixtures" / "sms_sample.txt", "rb") as f:
            r = c.post("/api/import", files={"file": ("sms_sample.txt", f, "text/plain")}, data={"kind": "sms"})
        check(r.status_code == 200 and r.json()["inserted"] == 9, f"SMS import inserted {r.json().get('inserted')}")
        r = c.get("/api/activity", params={"limit": 3}).json()
        check(r["items"] and r["items"][0]["client"] == "web", f"activity attributed to '{r['items'][0]['client']}'")
        t = c.post("/api/mcp/tokens", json={"name": "e2e host"}).json()
        check(t["token"].startswith("fm_"), "personal MCP token created")
        return email, t["token"]


async def remote_mcp_layer(token: str) -> None:
    import uvicorn

    from agent import MCPConnection
    from api.main import create_app

    print("Remote MCP endpoint over HTTP")
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        try:
            async with MCPConnection.http(url) as conn:
                await conn.list_tools()
            check(False, "endpoint refuses connections without a token")
        except Exception:
            check(True, "endpoint refuses connections without a token")
        async with MCPConnection.http(url, headers={"Authorization": f"Bearer {token}"}) as conn:
            out = await conn.call_tool("add_transaction", {"date": "2026-09-16", "amount": 275, "merchant": "Blue Tokai", "description": "coffee beans"})
            check(out.ok and out.data["transaction"]["category"] == "Food & Dining", "add_transaction over the remote endpoint")
            client = out.data["transaction"]["client"]
            check(bool(client) and client != "web", f"write attributed to the MCP client ('{client}')")
            out = await conn.call_tool("query_transactions", {"question": "top 3 merchants last month"})
            check(out.ok and len(out.data["rows"]) == 3, "query_transactions over HTTP")
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def main() -> int:
    try:
        asyncio.run(stdio_layer())
        asyncio.run(agent_layer())
        _, token = api_layer()
        asyncio.run(remote_mcp_layer(token))
    finally:
        CLUSTER.destroy()
    print()
    if FAILS:
        print(f"{len(FAILS)} check(s) failed: {FAILS}")
        return 1
    print("all layers ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
