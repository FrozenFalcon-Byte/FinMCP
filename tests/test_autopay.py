"""Autopay: the standing instruction, and the entries it files."""
from datetime import date, timedelta

import pytest

from finmcp.db.repository import Repository
from finmcp.services.autopay import run_autopay
from finmcp.services.recurring import list_recurring

TODAY = date(2026, 9, 17)


def bill(repo: Repository, merchant: str, months: tuple[int, ...], amount: float = 649.0) -> None:
    for m in months:
        repo.insert_transaction(date=date(2026, m, 12).isoformat(), amount=amount, merchant=merchant, direction="debit")


def test_a_detected_bill_can_be_put_on_autopay(repo: Repository):
    bill(repo, "NETFLIX", (5, 6, 7, 8, 9))
    found = next(i for i in list_recurring(repo, TODAY)["items"] if i["merchant"] == "NETFLIX")
    assert found["autopay"] is None and found["next_due"] == "2026-10-12"

    repo.upsert_autopay(merchant="NETFLIX", amount=found["amount"], cadence=found["cadence"],
                        cadence_days=found["cadence_days"], category=found["category"], next_due=found["next_due"])
    again = next(i for i in list_recurring(repo, TODAY)["items"] if i["merchant"] == "NETFLIX")
    assert again["autopay"]["active"] and again["autopay"]["posted_count"] == 0
    assert list_recurring(repo, TODAY)["autopay_count"] == 1


def test_it_files_only_cycles_whose_date_has_passed(repo: Repository):
    bill(repo, "SPOTIFY", (5, 6, 7, 8, 9), amount=199)
    repo.upsert_autopay(merchant="SPOTIFY", amount=199, cadence="monthly", cadence_days=30,
                        category=None, next_due=(date.today() + timedelta(days=5)).isoformat())
    assert run_autopay(repo)["posted_count"] == 0          # not due yet: nothing is written

    repo.upsert_autopay(merchant="SPOTIFY", amount=199, cadence="monthly", cadence_days=30,
                        category=None, next_due=date.today().isoformat())
    run = run_autopay(repo)
    assert run["posted_count"] == 1 and run["posted"][0]["date"] == date.today().isoformat()
    rule = repo.get_autopay("spotify")
    assert rule["posted_count"] == 1 and str(rule["next_due"]) > date.today().isoformat()


def test_running_twice_does_not_pay_twice(repo: Repository):
    """The fingerprint is the one an imported statement would carry, so the second run recognises its own work."""
    repo.upsert_autopay(merchant="JIO", amount=399, cadence="monthly", cadence_days=30,
                        category=None, next_due=date.today().isoformat())
    assert run_autopay(repo)["posted_count"] == 1
    # wind it back to the same cycle and run again: the ledger already has that entry
    repo.upsert_autopay(merchant="JIO", amount=399, cadence="monthly", cadence_days=30,
                        category=None, next_due=date.today().isoformat())
    second = run_autopay(repo)
    assert second["posted_count"] == 0 and second["skipped_count"] == 1
    rows = repo._all("SELECT id FROM transactions WHERE user_id = %s AND merchant = 'JIO'", (repo.user_id,))
    assert len(rows) == 1


def test_a_categorised_bill_files_with_its_category(repo: Repository):
    """The category rides along, filed the way the ledger files anything it knows from history."""
    repo.upsert_category("Personal Care")
    repo.upsert_autopay(merchant="CULT.FIT", amount=1500, cadence="monthly", cadence_days=30,
                        category="Personal Care", next_due=date.today().isoformat())
    assert run_autopay(repo)["posted_count"] == 1
    row = repo._one("SELECT category, category_source, source FROM v_transactions WHERE user_id = %s AND merchant = 'CULT.FIT'", (repo.user_id,))
    assert row["category"] == "Personal Care" and row["category_source"] == "memory" and row["source"] == "autopay"


def test_a_rule_left_alone_catches_up_but_not_forever(repo: Repository):
    """A year of missed cycles should not write twelve entries the moment you open the app."""
    repo.upsert_autopay(merchant="GYM", amount=1500, cadence="monthly", cadence_days=30,
                        category=None, next_due=(date.today() - timedelta(days=400)).isoformat())
    run = run_autopay(repo)
    assert run["posted_count"] == 6                         # MAX_CATCH_UP
    assert repo.get_autopay("gym")["posted_count"] == 6


def test_turning_it_off_keeps_the_history(repo: Repository):
    repo.upsert_autopay(merchant="HOTSTAR", amount=299, cadence="monthly", cadence_days=30,
                        category=None, next_due=date.today().isoformat())
    run_autopay(repo)
    off = repo.set_autopay_active("HOTSTAR", False)
    assert off["active"] is False and off["posted_count"] == 1
    assert run_autopay(repo)["posted_count"] == 0           # inactive rules are not due
    assert repo.set_autopay_active("HOTSTAR", True)["posted_count"] == 1


def test_clearing_forgets_the_rule_but_not_the_entries(repo: Repository):
    repo.upsert_autopay(merchant="ICICI CARD", amount=5000, cadence="monthly", cadence_days=30,
                        category=None, next_due=date.today().isoformat())
    run_autopay(repo)
    assert repo.delete_autopay("ICICI CARD") is True
    assert repo.get_autopay("icici card") is None
    assert repo._all("SELECT id FROM transactions WHERE user_id = %s AND merchant = 'ICICI CARD'", (repo.user_id,))


def test_the_list_reports_what_a_bill_has_cost(repo: Repository):
    bill(repo, "RENT", (5, 6, 7, 8, 9), amount=25000)
    found = next(i for i in list_recurring(repo, TODAY)["items"] if i["merchant"] == "RENT")
    assert found["occurrences"] == 5 and found["paid_total"] == 125000
    assert found["count_this_year"] == 5 and found["paid_this_year"] == 125000
    assert found["first_date"] == "2026-05-12"


@pytest.mark.parametrize("tool", ["set_autopay", "clear_autopay", "run_autopay"])
def test_the_tools_are_registered(server, tool):
    from tests.conftest import connect, tool_names

    async def run():
        async with connect(server) as client:
            assert tool in tool_names(await client.list_tools())

    import anyio
    anyio.run(run)
