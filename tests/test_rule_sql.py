from datetime import date

import pytest

from finmcp.llm.rule_sql import UnsupportedQuestion, rule_based_sql

TODAY = date(2026, 9, 17)


def run(repo, question):
    sql, explanation = rule_based_sql(question, TODAY)
    cols, rows, _ = repo.select(sql)
    return sql, explanation, cols, rows


def test_total_spend_on_category_last_month(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "How much did I spend on groceries last month?")
    assert "Groceries" in sql and "2026-08-01" in sql and "2026-08-31" in sql
    assert cols[0] == "total" and rows[0][0] > 0
    assert "period: August 2026" in expl


def test_top_merchants(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "top 3 merchants this month")
    assert "GROUP BY merchant" in sql and "LIMIT 3" in sql
    assert len(rows) == 3 and rows[0][1] >= rows[1][1]


def test_breakdown_by_category(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "spending breakdown by category in august")
    assert "GROUP BY category_id" in sql and len(rows) > 5


def test_count_over_amount(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "how many transactions over 5000 in the last 90 days")
    assert "amount >= 5000" in sql and cols[0] == "transactions" and rows[0][0] >= 3


def test_merchant_listing(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "list my transactions at swiggy in the last 30 days")
    assert "merchant ILIKE '%swiggy%'" in sql and all("SWIGGY" in r[2] for r in rows) and rows


def test_largest_purchase(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "what was my biggest purchase in july 2026")
    assert "ORDER BY amount DESC LIMIT 1" in sql and len(rows) == 1


def test_income(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "how much income did I receive last month")
    assert "direction = 'credit'" in sql and rows[0][0] >= 95000


def test_monthly_trend(seeded_repo):
    sql, expl, cols, rows = run(seeded_repo, "monthly spending trend")
    assert cols[0] == "month" and len(rows) >= 3


def test_amount_suffix():
    sql, _ = rule_based_sql("transactions above 2k", TODAY)
    assert "amount >= 2000" in sql


def test_unsupported():
    with pytest.raises(UnsupportedQuestion):
        rule_based_sql("tell me a joke about my bank", TODAY)
