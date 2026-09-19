from datetime import date

from finmcp.db.seed import seed_demo_data


def test_seed_is_realistic_and_idempotent(repo):
    result = seed_demo_data(repo, days=90, end=date(2026, 9, 17))
    assert result["inserted"] > 180
    assert result["categorized"] / result["inserted"] > 0.85
    assert result["categories"] >= 19
    first, last = repo.date_bounds()
    assert first == "2026-06-20" and last == "2026-09-17"
    # salary every month
    rows, total = repo.list_transactions(merchant="ACME", direction="credit")
    assert total == 3
    # some deliberately opaque merchants remain for the review queue
    _, review = repo.list_transactions(needs_review_only=True, limit=1)
    assert review >= 3
    again = seed_demo_data(repo, days=90, end=date(2026, 9, 17))
    assert again["inserted"] == 0 and again["duplicates"] == result["inserted"]
