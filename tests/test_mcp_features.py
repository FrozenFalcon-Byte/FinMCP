"""The whole protocol, client and server: sampling, elicitation, roots, progress, logging, completion and
`subscriptions/listen`, driven through the app's own `MCPConnection` exactly as the web app and assistant use it."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import mcp.types as mt

from agent.host import roots_callback
from agent.mcp_client import MCPConnection
from finmcp.config import ROOT
from finmcp.server import create_server

from .conftest import make_server, make_settings

UNKNOWN = "Zqx Obscure Traders"


def elicit_with(content: dict | None, action: str = "accept", seen: list | None = None):
    async def handler(context, params):
        if seen is not None:
            seen.append(params.message)
        return mt.ElicitResult(action=action, content=content)
    return handler


def sample_with(answer: dict, seen: list | None = None):
    async def handler(context, params):
        if seen is not None:
            seen.append(params.messages[0].content.text)
        return mt.CreateMessageResult(role="assistant", content=mt.TextContent(type="text", text=json.dumps(answer)),
                                      model="test-model", stop_reason="endTurn")
    return handler


async def test_resolved_parameters_are_not_tool_arguments(server):
    async with MCPConnection.in_process(server) as conn:
        tools = {t.name: t for t in await conn.list_tools()}
        props = tools["add_transaction"].input_schema["properties"]
        assert "sampled" not in props and "answer" not in props and "merchant" in props
        assert "roots" not in tools["import_statement"].input_schema["properties"]


async def test_elicitation_files_an_unknown_merchant(server):
    asked: list[str] = []
    trace: list[dict] = []
    async with MCPConnection.in_process(server, elicitation=elicit_with({"category": "Shopping"}, seen=asked), trace=trace.append) as conn:
        out = await conn.call_tool("add_transaction", {"date": "2026-09-10", "amount": 999, "merchant": UNKNOWN})
    assert out.ok, out.text
    assert out.data["transaction"]["category"] == "Shopping" and out.data["asked"] == "accept"
    assert asked and UNKNOWN in asked[0]
    methods = [t["method"] for t in trace]
    assert "elicitation/create" in methods and "notifications/message" in methods


async def test_no_question_when_rules_are_confident(server):
    asked: list[str] = []
    async with MCPConnection.in_process(server, elicitation=elicit_with({"category": "Shopping"}, seen=asked)) as conn:
        out = await conn.call_tool("add_transaction", {"date": "2026-09-10", "amount": 250, "merchant": "Swiggy"})
    assert out.ok and out.data["asked"] is None and not asked
    assert out.data["transaction"]["category"] == "Food & Dining"


async def test_declined_question_still_records_the_transaction(server):
    async with MCPConnection.in_process(server, elicitation=elicit_with(None, action="decline")) as conn:
        out = await conn.call_tool("add_transaction", {"date": "2026-09-10", "amount": 40, "merchant": UNKNOWN})
    assert out.ok and out.data["asked"] == "decline" and out.data["transaction"]["id"]


async def test_sampling_borrows_the_clients_model(server):
    prompts: list[str] = []
    answer = {"1": {"category": "Entertainment", "confidence": 0.93, "reasoning": "sounds like a venue"}}
    async with MCPConnection.in_process(server, sampling=sample_with(answer, prompts), elicitation=elicit_with({"category": "Shopping"})) as conn:
        out = await conn.call_tool("add_transaction", {"date": "2026-09-10", "amount": 1200, "merchant": UNKNOWN})
    assert out.ok, out.text
    tx = out.data["transaction"]
    assert tx["category"] == "Entertainment" and out.data["categorization"]["source"] == "llm" and out.data["asked"] is None
    assert len(prompts) == 1 and UNKNOWN in prompts[0]


async def test_batch_categorization_is_one_sampling_round_with_progress(db, store):
    server = make_server(db, store, seed=False)
    plain = MCPConnection.in_process(server)
    async with plain:
        for i, m in enumerate(["Qqq Alpha", "Qqq Beta", "Qqq Alpha"]):
            await plain.call_tool("add_transaction", {"date": f"2026-09-0{i + 1}", "amount": 100 + i, "merchant": m, "auto_categorize": False})
    prompts: list[str] = []
    trace: list[dict] = []
    answer = {"1": {"category": "Shopping", "confidence": 0.9, "reasoning": "x"}, "2": {"category": "Health", "confidence": 0.8, "reasoning": "y"}}
    async with MCPConnection.in_process(server, sampling=sample_with(answer, prompts), trace=trace.append) as conn:
        out = await conn.call_tool("categorize_uncategorized", {"limit": 10})
    assert out.ok, out.text
    assert out.data["processed"] == 3 and out.data["categorized"] == 3 and out.data["provider"] == "sampling"
    assert len(prompts) == 1 and prompts[0].count("Qqq Alpha") == 1  # distinct merchants, one round trip
    assert sum(1 for t in trace if t["method"] == "notifications/progress") == 3


async def test_delete_asks_for_confirmation(server):
    async with MCPConnection.in_process(server) as plain:
        added = await plain.call_tool("add_transaction", {"date": "2026-09-10", "amount": 10, "merchant": "Swiggy"})
    tx_id = added.data["transaction"]["id"]
    async with MCPConnection.in_process(server, elicitation=elicit_with({"confirm": False})) as conn:
        out = await conn.call_tool("delete_transaction", {"transaction_id": tx_id})
        assert out.ok and out.data["deleted"] is False
    async with MCPConnection.in_process(server, elicitation=elicit_with({"confirm": True})) as conn:
        out = await conn.call_tool("delete_transaction", {"transaction_id": tx_id})
        assert out.ok and out.data["deleted"] is True


async def test_roots_limit_which_files_can_be_imported(server, tmp_path: Path):
    csv = ROOT / "fixtures" / "statement_sample.csv"
    async with MCPConnection.in_process(server, roots=roots_callback([tmp_path])) as conn:
        out = await conn.call_tool("parse_statement", {"file_path": str(csv)})
        assert not out.ok and "outside the client's roots" in out.text
        inside = tmp_path / "s.csv"
        inside.write_bytes(csv.read_bytes())
        out = await conn.call_tool("parse_statement", {"file_path": str(inside)})
        assert out.ok, out.text


async def test_completion_suggests_months(server):
    async with MCPConnection.in_process(server) as conn:
        months = await conn.complete_prompt_argument("monthly_spending_review", "month", "2026-0")
        assert months and all(m.startswith("2026-0") for m in months)
        via_template = await conn.complete_resource_argument("finmcp://transactions/{month}", "month", "")
        assert len(via_template) >= 6


async def test_listen_sees_writes_from_another_client(db, store):
    web = make_server(db, store, seed=False)
    uid = web.finmcp.tenant().user_id
    other = create_server(make_settings(), db=db, user_id=uid, client="claude-desktop")
    seen: list[str] = []
    async with MCPConnection.in_process(web) as listener, MCPConnection.in_process(other) as writer:
        async def watch():
            async for uri in listener.listen(["finmcp://overview", "finmcp://goals"]):
                seen.append(uri)
                if "finmcp://overview" in seen:
                    return
        task = asyncio.create_task(watch())
        await asyncio.sleep(0.2)
        await writer.call_tool("add_transaction", {"date": "2026-09-10", "amount": 55, "merchant": "Swiggy"})
        await asyncio.wait_for(task, 5)
    assert "finmcp://overview" in seen and "finmcp://goals" not in seen
