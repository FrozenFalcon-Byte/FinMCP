"""The remote MCP endpoint: bearer tokens in, one account's tools out, over real HTTP."""
from __future__ import annotations

import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from agent import MCPConnection


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_api():
    from api.main import create_app

    port = _free_port()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 60
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=20)


def _register(base: str, name: str) -> tuple[str, str]:
    r = httpx.post(f"{base}/api/auth/register", json={"name": name, "email": f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com",
                                                     "password": "plain words ledger", "sample_data": False}, timeout=30)
    assert r.status_code == 201, r.text
    jwt_token = r.json()["access_token"]
    t = httpx.post(f"{base}/api/mcp/tokens", json={"name": "pytest host"}, headers={"Authorization": f"Bearer {jwt_token}"}, timeout=30)
    assert t.status_code == 201, t.text
    return jwt_token, t.json()["token"]


async def test_remote_mcp_needs_a_token(live_api: str):
    r = httpx.post(f"{live_api}/mcp", json={}, headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401 and "Bearer" in r.headers.get("www-authenticate", "")
    r = httpx.post(f"{live_api}/mcp", json={}, headers={"Authorization": "Bearer fm_nope", "Accept": "application/json, text/event-stream"})
    assert r.status_code == 401


async def test_remote_mcp_scopes_to_the_token_owner(live_api: str):
    _, ada_tok = _register(live_api, "Ada")
    _, grace_tok = _register(live_api, "Grace")
    async with MCPConnection.http(f"{live_api}/mcp", headers={"Authorization": f"Bearer {ada_tok}"}) as conn:
        tools = await conn.list_tools()
        assert len(tools) >= 20 and conn.instructions and "FinMCP" in conn.instructions
        out = await conn.call_tool("add_transaction", {"date": "2026-09-12", "amount": 450, "merchant": "Swiggy", "description": "UPI/SWIGGY/1/Food"})
        assert out.ok, out.text
        tx = out.data["transaction"]
        assert tx["category"] == "Food & Dining" and tx["client"]  # named after the MCP client that connected
        status = await conn.read_resource_json("finmcp://status")
        assert status["transactions"] == 1
        overview = await conn.read_resource_json("finmcp://overview")
        assert overview["spent"] == 450
        act = await conn.call_tool("recent_activity", {"limit": 3})
        assert act.ok and act.data["items"][0]["client"] == tx["client"]
        bad = await conn.call_tool("run_sql", {"sql": "DELETE FROM transactions"})
        assert not bad.ok
    async with MCPConnection.http(f"{live_api}/mcp", headers={"Authorization": f"Bearer {grace_tok}"}) as conn:
        out = await conn.call_tool("list_transactions", {"limit": 5})
        assert out.ok and out.data["total"] == 0
        out = await conn.call_tool("run_sql", {"sql": "SELECT COUNT(*) AS n FROM transactions"})
        assert out.ok and out.data["rows"] == [[0]]


async def test_session_jwt_also_works_on_mcp(live_api: str):
    jwt_token, _ = _register(live_api, "Jay")
    async with MCPConnection.http(f"{live_api}/mcp", headers={"Authorization": f"Bearer {jwt_token}"}) as conn:
        out = await conn.call_tool("list_categories", {})
        assert out.ok and len(out.data["categories"]) >= 19
