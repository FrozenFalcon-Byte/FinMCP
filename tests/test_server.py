import json

from tests.conftest import connect, result_data, result_text, tool_names

EXPECTED_TOOLS = {
    "add_transaction", "update_transaction", "delete_transaction", "list_transactions", "list_categories", "set_budget",
    "categorize_transaction", "categorize_uncategorized", "query_transactions", "run_sql", "get_summary", "get_budget_summary",
}


async def test_surface(server):
    async with connect(server) as client:
        tools = tool_names(await client.list_tools())
        assert set(tools) >= EXPECTED_TOOLS
        resources = await client.list_resources()
        uris = {str(r.uri) for r in getattr(resources, "resources", resources)}
        assert {"finmcp://categories", "finmcp://transactions/recent", "finmcp://summary/monthly", "finmcp://schema", "finmcp://status"} <= uris
        templates = await client.list_resource_templates()
        tpl = [getattr(t, "uri_template", None) or getattr(t, "uriTemplate", None) for t in getattr(templates, "resource_templates", getattr(templates, "resourceTemplates", templates))]
        assert "finmcp://transactions/{month}" in tpl
        prompts = await client.list_prompts()
        names = {p.name for p in getattr(prompts, "prompts", prompts)}
        assert {"monthly_spending_review", "categorize_uncategorized", "budget_planning"} <= names


async def test_add_list_update_delete(server):
    async with connect(server) as client:
        r = await client.call_tool("add_transaction", {"date": "2026-09-16", "amount": 350, "merchant": "Swiggy", "description": "UPI/SWIGGY/1/Food order"})
        assert not r.is_error, result_text(r)
        data = result_data(r)
        tx = data["transaction"]
        assert tx["category"] == "Food & Dining" and data["categorization"]["source"] == "rule"

        r = await client.call_tool("list_transactions", {"merchant": "swiggy", "period": "this month", "limit": 5})
        data = result_data(r)
        assert data["total"] >= 1 and any(t["id"] == tx["id"] for t in data["transactions"])

        r = await client.call_tool("update_transaction", {"transaction_id": tx["id"], "category": "groceries", "amount": 360})
        data = result_data(r)
        assert data["transaction"]["category"] == "Groceries" and data["transaction"]["amount"] == 360
        assert data["feedback"]["source"] == "user"

        r = await client.call_tool("delete_transaction", {"transaction_id": tx["id"]})
        assert result_data(r)["deleted"] is True
        r = await client.call_tool("delete_transaction", {"transaction_id": tx["id"]})
        assert r.is_error and "not found" in result_text(r)


async def test_validation_errors(server):
    async with connect(server) as client:
        r = await client.call_tool("add_transaction", {"date": "16/09/2026", "amount": 10, "merchant": "x"})
        assert r.is_error and "ISO date" in result_text(r)
        r = await client.call_tool("add_transaction", {"date": "2026-09-16", "amount": -5, "merchant": "x"})
        assert r.is_error


async def test_summaries(server):
    async with connect(server) as client:
        r = await client.call_tool("get_summary", {"period": "last month", "group_by": "category"})
        data = result_data(r)
        assert data["totals"]["spent"] > 0 and data["breakdown"]
        r = await client.call_tool("get_budget_summary", {})
        data = result_data(r)
        assert data["categories"] and "used_pct" in next(c for c in data["categories"] if "budget_limit" in c)
        r = await client.call_tool("set_budget", {"category": "food", "monthly_limit": 9000})
        assert result_data(r)["category"]["budget_limit"] == 9000


async def test_query_and_sql(server):
    async with connect(server) as client:
        r = await client.call_tool("query_transactions", {"question": "how much did I spend on food last month"})
        assert not r.is_error, result_text(r)
        data = result_data(r)
        assert data["provider"] == "rules" and data["rows"][0][0] > 0 and "Food & Dining" in data["sql"]
        r = await client.call_tool("query_transactions", {"question": "sing me a song"})
        assert r.is_error and "run_sql" in result_text(r)
        r = await client.call_tool("run_sql", {"sql": "SELECT COUNT(*) AS n FROM v_transactions"})
        assert result_data(r)["rows"][0][0] > 100
        r = await client.call_tool("run_sql", {"sql": "DELETE FROM transactions"})
        assert r.is_error and "SELECT" in result_text(r)


async def test_categorize_uncategorized(server):
    async with connect(server) as client:
        r = await client.call_tool("list_transactions", {"uncategorized_only": True, "limit": 5})
        before = result_data(r)["total"]
        assert before >= 1
        r = await client.call_tool("categorize_uncategorized", {"limit": 10})
        data = result_data(r)
        assert data["processed"] >= 1 and data["provider"] == "rules"
        tx_id = data["results"][0]["transaction_id"]
        r = await client.call_tool("categorize_transaction", {"transaction_id": tx_id})
        assert not r.is_error


async def test_resources_and_prompts(server):
    async with connect(server) as client:
        r = await client.read_resource("finmcp://categories")
        cats = json.loads(r.contents[0].text)
        assert any(c["name"] == "Groceries" for c in cats)
        r = await client.read_resource("finmcp://transactions/recent")
        assert json.loads(r.contents[0].text)["total"] > 100
        r = await client.read_resource("finmcp://transactions/2026-08")
        assert json.loads(r.contents[0].text)["total"] > 30
        r = await client.read_resource("finmcp://schema")
        assert "v_transactions" in r.contents[0].text
        r = await client.read_resource("finmcp://status")
        st = json.loads(r.contents[0].text)
        assert st["llm_provider"] == "rules" and st["transactions"] > 100
        r = await client.read_resource("finmcp://summary/monthly")
        assert len(json.loads(r.contents[0].text)) > 10
        p = await client.get_prompt("monthly_spending_review", {"month": "2026-08"})
        text = p.messages[0].content.text
        assert "get_summary" in text and "2026-08" in text
        p = await client.get_prompt("budget_planning", {})
        assert "set_budget" in p.messages[0].content.text
