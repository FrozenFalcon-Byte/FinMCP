
from agent import Agent, LocalDriver, MCPConnection, ScriptedDriver
from agent.prompts import build_system_prompt
from finmcp.db.accounts import AccountStore
from tests import conftest


def make_server():
    return conftest.make_server(conftest._DB, AccountStore(conftest._DB))


async def collect(agent, text, cid=None):
    return [ev async for ev in agent.run(text, cid)]


def types(evs):
    return [e["type"] for e in evs]


async def test_prepare_builds_grounded_prompt():
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, ScriptedDriver([]))
        await agent.prepare()
        names = {t["name"] for t in agent.tools}
        assert {"get_summary", "query_transactions", "import_statement"} <= names
        assert all("input_schema" in t and t["input_schema"].get("type") == "object" for t in agent.tools)
        assert "Groceries" in agent.system and "v_transactions" in agent.system and "Today is" in agent.system
        assert conn.instructions and "FinMCP" in conn.instructions


async def test_tool_round_trip_and_history():
    driver = ScriptedDriver([
        [{"type": "text", "text": "Let me check last month."}, {"type": "tool_use", "name": "get_summary", "input": {"period": "last month"}}],
        [{"type": "text", "text": "You spent a fair amount."}],
    ])
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, driver)
        evs = await collect(agent, "How much did I spend last month?")
        kinds = types(evs)
        assert kinds[:2] == ["text_delta", "text_delta"]
        assert "tool_call" in kinds and "tool_result" in kinds and kinds[-1] == "done"
        call = next(e for e in evs if e["type"] == "tool_call")
        res = next(e for e in evs if e["type"] == "tool_result")
        assert call["name"] == "get_summary" and call["input"] == {"period": "last month"}
        assert res["ok"] and res["id"] == call["id"] and '"spent"' in res["preview"] and res["data"]["totals"]["spent"] > 0
        done = evs[-1]
        assert done["text"] == "Let me check last month.\n\nYou spent a fair amount." and done["iterations"] == 2 and done["stop_reason"] == "end_turn"
        conv = agent.conversation(done["conversation_id"])
        roles = [m["role"] for m in conv.messages]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert conv.messages[1]["content"][1]["type"] == "tool_use"
        tr = conv.messages[2]["content"][0]
        assert tr["type"] == "tool_result" and tr["tool_use_id"] == call["id"] and "is_error" not in tr
        # second driver call saw the full history including the tool result
        assert len(driver.calls[1]["messages"]) == 3
        # transcript view
        t = agent.transcript(done["conversation_id"])
        assert [x["type"] for x in t] == ["text", "text", "tool_call", "tool_result", "text"]


async def test_tool_error_is_reported_back_to_model():
    driver = ScriptedDriver([
        [{"type": "tool_use", "name": "delete_transaction", "input": {"transaction_id": 999999}}],
        [{"type": "text", "text": "That transaction does not exist."}],
    ])
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, driver)
        evs = await collect(agent, "delete transaction 999999")
        res = next(e for e in evs if e["type"] == "tool_result")
        assert res["ok"] is False and "not found" in res["preview"]
        conv = agent.conversation(evs[-1]["conversation_id"])
        assert conv.messages[2]["content"][0]["is_error"] is True


async def test_unknown_tool_and_max_iterations():
    driver = ScriptedDriver([[{"type": "tool_use", "name": "get_summary", "input": {}}]] * 3)
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, driver, max_iterations=3)
        evs = await collect(agent, "loop forever")
        assert sum(1 for e in evs if e["type"] == "tool_call") == 3
        assert any(e["type"] == "error" and "Stopped after 3" in e["message"] for e in evs)
        assert evs[-1]["type"] == "done"
    driver = ScriptedDriver([[{"type": "tool_use", "name": "no_such_tool", "input": {}}], [{"type": "text", "text": "ok"}]])
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, driver)
        evs = await collect(agent, "call a missing tool")
        res = next(e for e in evs if e["type"] == "tool_result")
        assert res["ok"] is False


async def test_driver_failure_rolls_back_user_turn():
    driver = ScriptedDriver([])  # raises DriverError immediately
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, driver)
        evs = await collect(agent, "hello", "conv1")
        assert evs[0]["type"] == "error" and evs[0]["fatal"] and evs[-1]["type"] == "done"
        assert agent.conversation("conv1").messages == []


async def test_conversation_reset_and_ids():
    driver = ScriptedDriver([[{"type": "text", "text": "hi"}], [{"type": "text", "text": "again"}]])
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, driver)
        evs = await collect(agent, "hello", "abc")
        assert evs[-1]["conversation_id"] == "abc" and agent.conversation("abc").title == "hello"
        await collect(agent, "more", "abc")
        assert agent.conversation("abc").turns == 2 and len(agent.conversation("abc").messages) == 4
        assert agent.reset("abc") is True and agent.reset("abc") is False


async def test_local_driver_end_to_end():
    async with MCPConnection.in_process(make_server()) as conn:
        agent = Agent(conn, LocalDriver())
        evs = await collect(agent, "how much did I spend on food last month?")
        call = next(e for e in evs if e["type"] == "tool_call")
        assert call["name"] == "query_transactions"
        done = evs[-1]
        assert "| total |" in done["text"] and "```sql" in done["text"] and "built-in query engine" in done["text"]
        evs = await collect(agent, "which budgets am I close to blowing?")
        assert next(e for e in evs if e["type"] == "tool_call")["name"] == "get_budget_summary"
        assert "| category | spent | limit |" in evs[-1]["text"]
        evs = await collect(agent, "give me an overview of this month")
        assert next(e for e in evs if e["type"] == "tool_call")["name"] == "get_summary"
        assert "spent" in evs[-1]["text"]
        evs = await collect(agent, "sing me a song about my bank")
        assert "I couldn't answer that" in evs[-1]["text"]


async def test_stdio_connection_smoke():
    async with MCPConnection.stdio(args=("--seed-if-empty", "--llm", "rules", "--client", "pytest-stdio")) as conn:
        tools = await conn.list_tools()
        assert any(t.name == "get_summary" for t in tools)
        out = await conn.call_tool("get_summary", {"period": "last month"})
        assert out.ok and out.data["totals"]["spent"] > 0
        cats = await conn.read_resource_json("finmcp://categories")
        assert any(c["name"] == "Income" for c in cats)
        assert "get_summary" in await conn.get_prompt_text("monthly_spending_review", {"month": "2026-08"})


def test_prompt_builder():
    s = build_system_prompt(currency="INR", categories=[{"name": "Food & Dining", "kind": "expense", "budget_limit": 8000}], server_instructions="Be nice.")
    assert "Food & Dining (expense, budget 8,000/month)" in s and "Be nice." in s and "INR" in s
