import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(scope="module")
def client():
    import uuid

    from api.main import create_app

    with TestClient(create_app()) as c:
        email = f"test-{uuid.uuid4().hex[:6]}@example.com"
        r = c.post("/api/auth/register", json={"name": "Test User", "email": email, "password": "correct horse", "sample_data": True})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        c.email = email  # type: ignore[attr-defined]
        yield c


def test_health_and_status(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["driver"] == "local" and h["authenticated"] and h["tools"] >= 15 and h["status"]["transactions"] > 100
    assert h["user"]["email"] == client.email and h["auth_mode"] == "local" and h["rls"] == "enforced"
    s = client.get("/api/status").json()
    assert s["llm_provider"] == "rules"


def test_transactions_crud(client):
    r = client.post("/api/transactions", json={"date": "2026-09-15", "amount": 420, "merchant": "Swiggy", "description": "UPI/SWIGGY/1/Food"})
    assert r.status_code == 201, r.text
    tx = r.json()["transaction"]
    assert tx["category"] == "Food & Dining"
    r = client.get("/api/transactions", params={"merchant": "swiggy", "period": "this month", "limit": 5})
    assert r.status_code == 200 and any(t["id"] == tx["id"] for t in r.json()["transactions"])
    r = client.patch(f"/api/transactions/{tx['id']}", json={"category": "groceries"})
    assert r.json()["transaction"]["category"] == "Groceries" and r.json()["feedback"]["source"] == "user"
    r = client.post(f"/api/transactions/{tx['id']}/categorize", params={"force": True})
    assert r.json()["category"] == "Groceries"
    r = client.delete(f"/api/transactions/{tx['id']}")
    assert r.json()["deleted"] is True
    r = client.delete(f"/api/transactions/{tx['id']}")
    assert r.status_code == 400 and "not found" in r.json()["detail"]
    r = client.post("/api/transactions", json={"date": "15/09/2026", "amount": 1, "merchant": "x"})
    assert r.status_code == 400 and "ISO date" in r.json()["detail"]


def test_summaries_budget_alerts_query(client):
    s = client.get("/api/summary", params={"period": "last month"}).json()
    assert s["totals"]["spent"] > 0 and s["breakdown"]
    b = client.get("/api/budget").json()
    assert b["categories"]
    a = client.get("/api/alerts").json()
    assert "alerts" in a and a["alert_count"] >= 0
    q = client.get("/api/query", params={"question": "top 3 merchants last month"}).json()
    assert len(q["rows"]) == 3
    cats = client.get("/api/categories").json()
    assert any(c["name"] == "Groceries" for c in cats)
    r = client.put("/api/categories/Groceries/budget", json={"monthly_limit": 13000})
    assert r.json()["category"]["budget_limit"] == 13000


def test_chat_stream_and_transcript(client):
    with client.stream("POST", "/api/chat", json={"message": "top 3 merchants last month"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in r.iter_lines() if line]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "conversation" and "tool_call" in kinds and kinds[-1] == "done"
    cid = events[0]["conversation_id"]
    t = client.get(f"/api/chat/{cid}").json()
    assert t["turns"] == 1 and any(m["type"] == "tool_call" for m in t["messages"])
    assert any(c["conversation_id"] == cid for c in client.get("/api/chats").json())
    assert client.delete(f"/api/chat/{cid}").json()["reset"] is True
    assert client.get(f"/api/chat/{cid}").status_code == 404
    p = client.get("/api/prompts").json()
    assert any(x["name"] == "monthly_spending_review" for x in p)
    r = client.post("/api/prompts/monthly_spending_review", json={"arguments": {"month": "2026-08"}})
    assert "2026-08" in r.json()["text"]


def test_imports(client):
    with open(FIXTURES / "statement_sample.csv", "rb") as f:
        r = client.post("/api/import/preview", files={"file": ("statement_sample.csv", f, "text/csv")}, data={"kind": "auto"})
    assert r.status_code == 200, r.text
    prev = r.json()
    assert prev["parsed"] == 12 and prev["upload_path"]
    r = client.post("/api/import", data={"upload_path": prev["upload_path"], "kind": "auto"})
    assert r.json()["inserted"] == 12
    r = client.post("/api/import", data={"upload_path": "/etc/passwd", "kind": "auto"})
    assert r.status_code == 400
    r = client.post("/api/import/text", json={"text": "Rs.450.00 debited from a/c **4321 on 12-09-26 to VPA swiggy@ybl (UPI Ref No 1). -HDFC Bank", "kind": "sms", "dry_run": True})
    assert r.json()["dry_run"] and r.json()["parsed"] == 1
    assert client.get("/api/imports").json()[0]["source_name"].endswith("statement_sample.csv")


def test_overview_recurring_activity(client):
    o = client.get("/api/overview").json()
    assert o["spent"] > 0 and o["month"]["days_left"] >= 0 and o["safe_to_spend"]["basis"] in {"budget", "average", "none"}
    assert len(o["top_categories"]) >= 1 and len(o["insights"]) >= 1 and isinstance(o["upcoming"], list) and len(o["recent"]) == 6
    r = client.get("/api/recurring").json()
    assert r["count"] >= 5 and r["monthly_expenses"] > 0
    names = {i["merchant"] for i in r["items"]}
    assert "NETFLIX" in names and "RENT - MR SHARMA" in names and all(i["cadence"] in {"weekly", "fortnightly", "monthly", "quarterly", "yearly"} for i in r["items"])
    a = client.get("/api/activity", params={"limit": 5}).json()
    assert len(a["items"]) == 5 and all(i["client"] in {"web", "seed", "assistant"} or i["client"] for i in a["items"])
    assert any(c["client"] == "web" for c in a["clients"])


def test_goals_crud(client):
    r = client.post("/api/goals", json={"name": "Trip to Japan", "target": 200000, "saved": 25000, "due": "2027-04-01", "icon": "🗾"})
    assert r.status_code == 201, r.text
    g = r.json()["goal"]
    assert g["saved"] == 25000 and g["due"] == "2027-04-01"
    r = client.post(f"/api/goals/{g['id']}/add", json={"amount": 5000})
    assert r.json()["goal"]["saved"] == 30000 and r.json()["reached"] is False
    r = client.patch(f"/api/goals/{g['id']}", json={"target": 150000})
    assert r.json()["goal"]["target"] == 150000 and r.json()["goal"]["name"] == "Trip to Japan"
    lst = client.get("/api/goals").json()
    mine = next(x for x in lst["goals"] if x["id"] == g["id"])
    assert mine["progress_pct"] == 20.0 and mine["monthly_needed"] > 0 and mine["months_left"] >= 1
    assert client.delete(f"/api/goals/{g['id']}").json()["deleted"] is True
    assert client.patch(f"/api/goals/{g['id']}", json={"target": 1}).status_code == 404


def test_export_csv(client):
    r = client.get("/api/export.csv", params={"period": "last month"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,date,amount,direction") and len(lines) > 40


def test_seed_demo_is_idempotent(client):
    r = client.post("/api/auth/seed-demo")
    assert r.status_code == 200 and r.json()["seeded"] is False


def test_mcp_inspector_and_elicitation_round_trip(client):
    import threading
    import time

    ov = client.get("/api/mcp/overview").json()
    web = ov["sessions"][0]
    assert web["client"] == "finmcp-web" and {"elicitation", "roots"} <= set(web["offers"]) and web["protocol"]
    assert "finmcp://overview" in ov["subscribed"]

    result: dict = {}
    t = threading.Thread(target=lambda: result.update(r=client.post("/api/transactions", json={
        "date": "2026-09-15", "amount": 777, "merchant": "Zqx Obscure Traders"})))
    t.start()
    question = None
    for _ in range(100):
        qs = client.get("/api/mcp/elicitations").json()["questions"]
        if qs:
            question = qs[0]
            break
        time.sleep(0.05)
    assert question and "Zqx Obscure Traders" in question["message"] and question["client"] == "web"
    assert "Shopping" in question["schema"]["properties"]["category"]["enum"]
    assert client.post(f"/api/mcp/elicitations/{question['id']}", json={"action": "accept", "content": {"category": "Shopping"}}).json()["ok"]
    t.join(10)
    r = result["r"]
    assert r.status_code == 201, r.text
    assert r.json()["transaction"]["category"] == "Shopping" and r.json()["asked"] == "accept"
    assert client.post(f"/api/mcp/elicitations/{question['id']}", json={"action": "cancel"}).status_code == 404

    trace = client.get("/api/mcp/trace").json()
    assert {"initialize", "tools/call", "elicitation/create", "subscriptions/listen", "notifications/resources/updated"} <= set(trace["stats"]["by_method"])
    assert trace["entries"][-1]["seq"] == trace["stats"]["total"]
    assert trace["stats"]["total"] >= len(trace["entries"])

    sch = client.get("/api/mcp/schema").json()
    assert any(t["name"] == "get_summary" for t in sch["tools"]) and sch["templates"]
    out = client.post("/api/mcp/call", json={"name": "get_summary", "arguments": {"period": "last month"}}).json()
    assert out["ok"] and out["data"]["totals"]
    assert client.get("/api/mcp/read", params={"uri": "finmcp://status"}).json()["text"]
    assert "get_summary" in client.post("/api/mcp/prompt", json={"name": "monthly_spending_review", "arguments": {"month": "2026-08"}}).json()["text"]
    assert client.get("/api/mcp/complete", params={"ref": "prompt", "name": "monthly_spending_review", "argument": "month", "value": "2026"}).json()["values"]


def test_emis_crud_and_schedule(client):
    made = client.post("/api/emis", json={"name": "Laptop", "amount": 5000, "start_date": "2026-01-10", "tenure_months": 12,
                                          "lender": "Bajaj Finserv", "principal": 55000}).json()["emi"]
    assert made["paid_count"] >= 1 and made["left_count"] == 12 - made["paid_count"] and made["interest"] == 5000
    assert made["outstanding"] == made["left_count"] * 5000 and made["ends_on"] == "2026-12-10"
    report = client.get("/api/emis").json()
    assert any(i["id"] == made["id"] for i in report["items"]) and report["monthly_total"] >= 5000
    edited = client.put(f"/api/emis/{made['id']}", json={"name": "Laptop", "amount": 4000, "start_date": "2026-01-10", "tenure_months": 12}).json()["emi"]
    assert edited["amount"] == 4000 and edited["principal"] is None
    assert client.get("/api/overview").json()["emi"]["monthly_total"] >= 4000
    assert client.delete(f"/api/emis/{made['id']}").json()["deleted"]
