"""First-run setup: the gate, what it writes, and what the dashboard does with it."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

PIXEL = "data:image/webp;base64," + "A" * 200


@pytest.fixture
def fresh():
    """An account with nothing in it, which is the only state where the setup shows at all."""
    from api.main import create_app

    with TestClient(create_app()) as c:
        r = c.post("/api/auth/register", json={"name": "New Person", "email": f"new-{uuid.uuid4().hex[:6]}@example.com",
                                               "password": "correct horse", "sample_data": False})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c


def test_a_new_account_is_not_onboarded(fresh):
    assert fresh.get("/api/auth/me").json()["user"]["onboarded_at"] is None


def test_setup_writes_the_profile_and_the_ledger(fresh):
    r = fresh.post("/api/auth/onboarding", json={
        "name": "Ada Lovelace", "currency": "INR", "monthly_income": 85000, "pay_day": 1, "keep_pct": 30,
        "avatar": PIXEL,
        "budgets": [{"category": "Rent & Housing", "monthly_limit": 24000}, {"category": "Food & Dining", "monthly_limit": 10000},
                    {"category": "Shopping"}],  # no amount: a pick without a number is not a budget
        "goal": {"name": "Japan trip", "target": 350000, "icon": "🎯"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["budgets"] == 2 and r.json()["goal"] == "Japan trip"

    user = r.json()["user"]
    assert user["onboarded_at"] is not None and user["name"] == "Ada Lovelace"
    assert user["monthly_income"] == 85000 and user["pay_day"] == 1 and user["keep_pct"] == 30 and user["avatar"] == PIXEL

    budgets = {c["category"]: c["budget_limit"] for c in fresh.get("/api/budget").json()["categories"] if c.get("budget_limit")}
    assert budgets == {"Rent & Housing": 24000, "Food & Dining": 10000}
    assert [g["name"] for g in fresh.get("/api/goals").json()["goals"]] == ["Japan trip"]


def test_setup_clears_the_example_budgets_nobody_chose(fresh):
    """A fresh ledger ships with example limits. After setup only the chosen ones survive."""
    before = {c["category"] for c in fresh.get("/api/budget").json()["categories"] if c.get("budget_limit")}
    assert len(before) > 2
    fresh.post("/api/auth/onboarding", json={"name": "Ada", "currency": "INR", "monthly_income": 85000,
                                            "budgets": [{"category": "Transport", "monthly_limit": 5000}]})
    after = {c["category"] for c in fresh.get("/api/budget").json()["categories"] if c.get("budget_limit")}
    assert after == {"Transport"}


def test_the_plan_drives_safe_to_spend_before_any_budget_exists(fresh):
    fresh.post("/api/auth/onboarding", json={"name": "Ada", "currency": "INR", "monthly_income": 100_000, "keep_pct": 20})
    sts = fresh.get("/api/overview").json()["safe_to_spend"]
    # Nothing spent yet, so the whole 80% is still there and the basis is the plan, not an average of no history.
    assert sts["basis"] == "plan" and sts["plan_total"] == 80_000 and sts["left"] == 80_000 and sts["per_day"]


def test_setup_needs_the_things_the_dashboard_cannot_work_without(fresh):
    assert fresh.post("/api/auth/onboarding", json={"name": "Ada", "currency": "INR"}).status_code == 422       # no income
    assert fresh.post("/api/auth/onboarding", json={"currency": "INR", "monthly_income": 10}).status_code == 422  # no name
    assert fresh.get("/api/auth/me").json()["user"]["onboarded_at"] is None  # and nothing was written


def test_a_photo_has_to_be_a_photo_and_has_to_be_small(fresh):
    assert fresh.patch("/api/auth/profile", json={"avatar": "javascript:alert(1)"}).status_code == 400
    assert fresh.patch("/api/auth/profile", json={"avatar": "data:image/png;base64," + "A" * 500_000}).status_code == 422
    assert fresh.patch("/api/auth/profile", json={"avatar": PIXEL}).json()["user"]["avatar"] == PIXEL
    assert fresh.patch("/api/auth/profile", json={"avatar": ""}).json()["user"]["avatar"] is None


def test_the_walkthrough_is_marked_seen_once(fresh):
    assert fresh.get("/api/auth/me").json()["user"]["tour_seen_at"] is None
    assert fresh.patch("/api/auth/profile", json={"tour_seen": True}).json()["user"]["tour_seen_at"] is not None
