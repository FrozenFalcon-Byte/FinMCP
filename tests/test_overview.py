from datetime import date

from finmcp.services.overview import get_overview

TODAY = date(2026, 9, 17)


def test_overview_on_seeded_ledger(seeded_repo):
    o = get_overview(seeded_repo, TODAY, currency="INR")
    assert o["today"] == "2026-09-17" and o["month"] == {"key": "2026-09", "label": "September 2026", "day": 17, "days": 30, "days_left": 13}
    assert o["spent"] > 0 and o["previous_spent"] > 0 and isinstance(o["pace_pct"], float)
    sts = o["safe_to_spend"]
    assert sts["basis"] == "budget" and sts["budget_total"] == 84000 and sts["per_day"] is not None
    assert abs(sts["per_day"] - round(sts["left"] / 14, 2)) < 0.02
    assert 1 <= len(o["top_categories"]) <= 3 and all(c["kind"] != "transfer" for c in o["top_categories"])
    assert o["insights"] and o["insights"][0]["kind"] == "pace"
    assert o["alerts"]["count"] >= 1 and len(o["recent"]) == 6 and o["needs_review"] >= 1
    assert o["recurring_count"] >= 5 and o["recurring_monthly"] > 0


def test_overview_on_empty_ledger(repo):
    o = get_overview(repo, TODAY)
    assert o["spent"] == 0 and o["pace_pct"] is None and o["safe_to_spend"]["basis"] == "budget"  # default budgets exist
    assert o["top_categories"] == [] and o["recent"] == [] and o["upcoming"] == []
