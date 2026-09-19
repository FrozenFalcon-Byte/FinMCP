from datetime import date

from finmcp.services.summary import check_budget_alerts, get_budget_summary, get_summary

TODAY = date(2026, 9, 17)


def test_summary_by_category(seeded_repo):
    s = get_summary(seeded_repo, "last month", "category", today=TODAY)
    assert s["period"]["start"] == "2026-08-01" and s["period"]["days"] == 31
    t = s["totals"]
    assert t["spent"] > 0 and t["received"] >= 95000 and t["transaction_count"] > 40
    assert abs(t["avg_daily_spend"] - t["spent"] / 31) < 0.02
    names = [b["category"] for b in s["breakdown"]]
    assert "Food & Dining" in names and "Rent & Housing" in names
    # transfers are listed but carry no share of consumption spend
    inv = next(b for b in s["breakdown"] if b["category"] == "Investments")
    assert inv["kind"] == "transfer" and inv["share_pct"] is None
    food = next(b for b in s["breakdown"] if b["category"] == "Food & Dining")
    assert food["budget_limit"] == 8000 and "budget_used_pct" in food


def test_summary_other_groupings(seeded_repo):
    m = get_summary(seeded_repo, "2026-08", "merchant", top=5, today=TODAY)
    assert len(m["breakdown"]) == 5 and m["breakdown"][0]["spent"] >= m["breakdown"][-1]["spent"]
    d = get_summary(seeded_repo, "last 7 days", "day", today=TODAY)
    assert all("day" in b for b in d["breakdown"])
    mo = get_summary(seeded_repo, "last 3 months", "month", today=TODAY)
    assert [b["month"] for b in mo["breakdown"]] == sorted(b["month"] for b in mo["breakdown"])
    # every time bucket carries both sides of the ledger so cash-flow charts need one call
    assert all({"spent", "received", "count", "credit_count"} <= set(b) for b in mo["breakdown"])
    assert sum(b["received"] for b in mo["breakdown"]) > 0


def test_budget_summary_and_alerts(seeded_repo):
    b = get_budget_summary(seeded_repo, None, today=TODAY)
    assert b["month"] == "2026-09" and b["is_current_month"] and b["days_elapsed"] == 17
    statuses = {c["status"] for c in b["categories"]}
    assert statuses & {"exceeded", "warning", "on_track"}
    food = next(c for c in b["categories"] if c["category"] == "Food & Dining")
    assert food["projected"] >= food["spent"] and food["budget_limit"] == 8000
    prev = get_budget_summary(seeded_repo, "last month", today=TODAY)
    assert prev["month"] == "2026-08" and not prev["is_current_month"] and prev["days_elapsed"] == 31
    alerts = check_budget_alerts(seeded_repo, None, today=TODAY)
    assert alerts["alert_count"] >= 1
    assert all(a["level"] in {"exceeded", "warning", "pace"} and a["message"] for a in alerts["alerts"])
