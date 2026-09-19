import pytest

from finmcp.db.repository import Repository, fingerprint_for, merchant_key


def test_insert_get_update_delete(repo):
    tx = repo.insert_transaction(date="2026-09-10", amount=250, merchant="Swiggy", description="UPI/SWIGGY/1/Food")
    assert tx.id and tx.direction == "debit" and tx.amount == 250 and tx.category is None
    cat = repo.get_category("Food & Dining")
    upd = repo.update_transaction(tx.id, category_id=cat.id, category_confidence=0.9, category_source="rule")
    assert upd.category == "Food & Dining" and upd.category_kind == "expense"
    assert repo.delete_transaction(tx.id) is True
    assert repo.get_transaction(tx.id) is None
    assert repo.delete_transaction(tx.id) is False


def test_update_rejects_unknown_fields(repo):
    tx = repo.insert_transaction(date="2026-09-10", amount=1, merchant="x")
    with pytest.raises(ValueError):
        repo.update_transaction(tx.id, bogus=1)
    with pytest.raises(ValueError):
        repo.update_transaction(999999, amount=2)


def test_fingerprint_dedupe(repo):
    fp = fingerprint_for("2026-09-10", 250, "debit", "SWIGGY", "raw")
    a = repo.insert_transaction(date="2026-09-10", amount=250, merchant="SWIGGY", fingerprint=fp, ignore_duplicate=True)
    b = repo.insert_transaction(date="2026-09-10", amount=250, merchant="SWIGGY", fingerprint=fp, ignore_duplicate=True)
    assert a is not None and b is None
    assert repo.count_transactions() == 1


def test_merchant_key_normalises():
    assert merchant_key("SWIGGY*ORDER 8812") == merchant_key("Swiggy") == "swiggy"
    assert merchant_key("POS 4321XXXX AMAZON PAY INDIA") == "amazon pay"


def test_list_filters(repo):
    food = repo.get_category("Food & Dining").id
    repo.insert_transaction(date="2026-09-01", amount=100, merchant="Swiggy", category_id=food)
    repo.insert_transaction(date="2026-09-05", amount=900, merchant="Amazon")
    repo.insert_transaction(date="2026-08-20", amount=5000, merchant="ACME", direction="credit")
    rows, total = repo.list_transactions(start="2026-09-01", end="2026-09-30")
    assert total == 2 and rows[0].merchant == "Amazon"  # date desc
    rows, total = repo.list_transactions(category="food & dining")
    assert total == 1 and rows[0].merchant == "Swiggy"
    rows, total = repo.list_transactions(merchant="ama")
    assert total == 1
    rows, total = repo.list_transactions(direction="credit")
    assert total == 1 and rows[0].amount == 5000
    rows, total = repo.list_transactions(min_amount=500, order="amount_asc")
    assert [r.amount for r in rows] == [900, 5000]
    rows, total = repo.list_transactions(uncategorized_only=True)
    assert total == 2
    rows, total = repo.list_transactions(limit=1, offset=1)
    assert total == 3 and len(rows) == 1


def test_select_is_read_only(repo):
    repo.insert_transaction(date="2026-09-01", amount=100, merchant="Swiggy")
    cols, rows, truncated = repo.select("SELECT merchant, amount FROM v_transactions")
    assert cols == ["merchant", "amount"] and rows == [["Swiggy", 100.0]] and truncated is False
    for bad in ["DELETE FROM transactions", "UPDATE transactions SET amount = 0", "SET ROLE postgres",
                "SELECT 1; DELETE FROM transactions", "INSERT INTO categories(name) VALUES ('x')",
                "DROP TABLE transactions", "WITH x AS (DELETE FROM transactions RETURNING *) SELECT * FROM x",
                "SELECT set_config('request.jwt.claims', '{}', true)", "SELECT pg_sleep(1)", "SELECT current_setting('request.jwt.claims')",
                "SELECT * FROM local_users", "SELECT * FROM pg_read_file('/etc/passwd')"]:
        with pytest.raises(ValueError):
            repo.select(bad)
    assert repo.count_transactions() == 1
    # CTEs work and the limit caps rows
    cols, rows, truncated = repo.select("WITH t AS (SELECT amount FROM transactions) SELECT * FROM t", limit=1)
    assert rows == [[100.0]]


def test_select_truncation(repo):
    for i in range(5):
        repo.insert_transaction(date="2026-09-01", amount=i + 1, merchant=f"m{i}")
    cols, rows, truncated = repo.select("SELECT id FROM transactions", limit=3)
    assert len(rows) == 3 and truncated is True


def test_merchant_memory(repo):
    food = repo.get_category("Food & Dining").id
    groc = repo.get_category("Groceries").id
    repo.remember_merchant("swiggy", food)
    repo.remember_merchant("swiggy", food)
    m = repo.recall_merchant("swiggy")
    assert m["hits"] == 2 and m["category"] == "Food & Dining"
    repo.remember_merchant("swiggy", groc)  # user changed their mind: hits reset
    assert repo.recall_merchant("swiggy")["hits"] == 1
    assert repo.recall_merchant("") is None


def test_totals_exclude_transfers(repo):
    inv = repo.get_category("Investments").id
    food = repo.get_category("Food & Dining").id
    repo.insert_transaction(date="2026-09-01", amount=10000, merchant="Zerodha", category_id=inv)
    repo.insert_transaction(date="2026-09-02", amount=300, merchant="Swiggy", category_id=food)
    repo.insert_transaction(date="2026-09-03", amount=95000, merchant="ACME", direction="credit")
    t = repo.totals("2026-09-01", "2026-09-30")
    assert t["spent"] == 300 and t["transfers_out"] == 10000 and t["received"] == 95000 and t["n"] == 3


def test_rls_hides_other_accounts(db, store, repo):
    from tests.conftest import new_user

    other = Repository(db, new_user(store), client="test")
    repo.insert_transaction(date="2026-09-01", amount=100, merchant="Mine")
    assert other.count_transactions() == 0
    cols, rows, _ = other.select("SELECT COUNT(*) AS n FROM transactions")
    assert rows == [[0]]
    cols, rows, _ = other.select("SELECT COUNT(*) AS n FROM v_transactions WHERE merchant = 'Mine'")
    assert rows == [[0]]
    assert other.get_transaction(repo.list_transactions()[0][0].id) is None


def test_goals(repo):
    g = repo.create_goal("Bike", 80000, saved=10000, due="2027-01-31", icon="🚲")
    assert g.saved == 10000 and g.due == "2027-01-31"
    g = repo.update_goal(g.id, saved=15000)
    assert g.saved == 15000 and repo.list_goals()[0].id == g.id
    with pytest.raises(ValueError):
        repo.update_goal(g.id, bogus=1)
    assert repo.delete_goal(g.id) and not repo.delete_goal(g.id)


def test_audit_carries_client(repo):
    repo.audit("test", "ping", "transaction", 1, {"x": 1})
    rows = repo.recent_audit(1)
    assert rows[0]["client"] == "test" and rows[0]["detail"] == {"x": 1}
    assert repo.clients_seen()[0]["client"] == "test"
