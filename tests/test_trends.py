"""Trends: the month-over-month view, and the care it takes with the month still in progress."""
from datetime import date

from finmcp.db.repository import Repository
from finmcp.services.trends import get_trends

TODAY = date(2026, 9, 15)  # halfway through a 30-day month


def spend(repo: Repository, month: int, amount: float, merchant: str = "SWIGGY", day: int = 4, category: str | None = None) -> None:
    cat = repo.get_category(category) if category else None
    repo.insert_transaction(date=date(2026, month, day).isoformat(), amount=amount, merchant=merchant,
                            direction="debit", category_id=cat.id if cat else None)


def test_the_window_is_calendar_months_ending_with_this_one(repo: Repository):
    spend(repo, 7, 100)
    out = get_trends(repo, months=4, today=TODAY)
    assert [m["month"] for m in out["series"]] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert out["window"] == {"from": "2026-06", "to": "2026-09"}
    assert out["series"][1]["spent"] == 100 and out["series"][1]["label"] == "Jul"


def test_a_month_with_nothing_in_it_is_still_a_month(repo: Repository):
    spend(repo, 8, 500)
    out = get_trends(repo, months=3, today=TODAY)
    assert [m["spent"] for m in out["series"]] == [0, 500, 0]
    assert [m["count"] for m in out["series"]] == [0, 1, 0]


def test_the_month_in_progress_is_marked_and_projected(repo: Repository):
    spend(repo, 9, 3000, day=2)
    out = get_trends(repo, months=3, today=TODAY)
    now = out["series"][-1]
    assert now["partial"] is True and now["spent"] == 3000
    assert now["projected"] == 6000  # 3000 over 15 of 30 days
    assert all(m["partial"] is False for m in out["series"][:-1])


def test_a_finished_month_is_not_projected(repo: Repository):
    spend(repo, 9, 3000, day=2)
    out = get_trends(repo, months=2, today=date(2026, 9, 30))
    assert out["series"][-1]["partial"] is False and out["series"][-1]["projected"] == 3000


def test_transfers_are_not_spending(repo: Repository):
    repo.upsert_category("Transfers", kind="transfer")
    spend(repo, 8, 900, merchant="TO SAVINGS", category="Transfers")
    spend(repo, 8, 100, merchant="SWIGGY")
    out = get_trends(repo, months=2, today=TODAY)
    assert out["series"][0]["spent"] == 100


def test_a_category_carries_its_own_row_across_the_window(repo: Repository):
    repo.upsert_category("Food & Dining")
    for m, amt in ((6, 200), (7, 300), (8, 400)):
        spend(repo, m, amt, category="Food & Dining")
    out = get_trends(repo, months=4, today=TODAY)
    food = next(c for c in out["categories"] if c["category"] == "Food & Dining")
    assert food["months"] == {"2026-06": 200, "2026-07": 300, "2026-08": 400, "2026-09": 0}
    assert food["total"] == 900 and food["share_pct"] == 100.0


def test_a_mover_is_measured_against_the_months_before_it(repo: Repository):
    repo.upsert_category("Shopping")
    for m in (6, 7, 8):
        spend(repo, m, 1000, merchant="AMAZON", category="Shopping")
    spend(repo, 9, 1000, merchant="AMAZON", day=2, category="Shopping")  # half a month in, so on pace for 2000
    out = get_trends(repo, months=4, today=TODAY)
    mover = out["movers"][0]
    assert mover["category"] == "Shopping"
    assert out["compare_is_projected"] is True
    assert mover["average"] == 1000 and mover["compared"] == 2000 and mover["change_pct"] == 100.0


def test_a_category_that_only_just_started_has_no_percentage(repo: Repository):
    repo.upsert_category("Health")
    spend(repo, 9, 500, merchant="APOLLO", day=2, category="Health")
    out = get_trends(repo, months=3, today=TODAY)
    health = next(c for c in out["categories"] if c["category"] == "Health")
    assert health["average"] == 0 and health["change_pct"] is None
    assert all(m["category"] != "Health" for m in out["movers"])


def test_categories_past_the_cap_are_merged_rather_than_dropped(repo: Repository):
    for i in range(5):
        repo.upsert_category(f"Cat{i}")
        spend(repo, 8, 100 * (i + 1), merchant=f"M{i}", category=f"Cat{i}")
    out = get_trends(repo, months=2, today=TODAY, top=2)
    assert [c["category"] for c in out["categories"]][-1] == "Everything else"
    assert sum(c["total"] for c in out["categories"]) == 1500
    assert out["categories"][-1]["aggregate"] is True


def test_what_was_kept_is_counted_from_income(repo: Repository):
    repo.insert_transaction(date="2026-08-01", amount=10000, merchant="SALARY", direction="credit")
    spend(repo, 8, 4000)
    out = get_trends(repo, months=3, today=TODAY)
    assert out["totals"]["received"] == 10000 and out["totals"]["saved_pct"] == 60.0
    assert any(i["kind"] == "saved" for i in out["insights"])


def test_an_empty_ledger_still_answers(repo: Repository):
    out = get_trends(repo, months=6, today=TODAY)
    assert len(out["series"]) == 6 and out["categories"] == []
    assert out["totals"]["saved_pct"] is None and out["totals"]["highest"] is None
    assert out["insights"] == []


def test_three_months_of_falling_spend_is_said_out_loud(repo: Repository):
    for m, amt in ((6, 3000), (7, 2000), (8, 1000)):
        spend(repo, m, amt)
    out = get_trends(repo, months=4, today=TODAY)
    assert any(i["kind"] == "streak" and i["tone"] == "good" for i in out["insights"])
