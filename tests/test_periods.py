from datetime import date

import pytest

from finmcp.services.periods import find_period_in_text, resolve_period

TODAY = date(2026, 9, 17)


@pytest.mark.parametrize("expr,start,end", [
    (None, "2026-09-01", "2026-09-17"),
    ("this month", "2026-09-01", "2026-09-17"),
    ("last month", "2026-08-01", "2026-08-31"),
    ("2026-07", "2026-07-01", "2026-07-31"),
    ("august", "2026-08-01", "2026-08-31"),
    ("Aug 2026", "2026-08-01", "2026-08-31"),
    ("october", "2025-10-01", "2025-10-31"),
    ("last 7 days", "2026-09-11", "2026-09-17"),
    ("last 30 days", "2026-08-19", "2026-09-17"),
    ("last 3 months", "2026-06-18", "2026-09-17"),
    ("ytd", "2026-01-01", "2026-09-17"),
    ("last year", "2025-01-01", "2025-12-31"),
    ("this week", "2026-09-14", "2026-09-17"),
    ("last week", "2026-09-07", "2026-09-13"),
    ("yesterday", "2026-09-16", "2026-09-16"),
    ("2026-08-10..2026-08-20", "2026-08-10", "2026-08-20"),
    ("2026-08-20 to 2026-08-10", "2026-08-10", "2026-08-20"),
    ("this quarter", "2026-07-01", "2026-09-17"),
    ("last quarter", "2026-04-01", "2026-06-30"),
    ("2025", "2025-01-01", "2025-12-31"),
])
def test_resolve_period(expr, start, end):
    p = resolve_period(expr, TODAY)
    assert p.start.isoformat() == start
    assert p.end.isoformat() == end
    assert p.days >= 1


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        resolve_period("whenever", TODAY)


def test_find_period_in_text():
    p, phrase = find_period_in_text("how much did I spend on food last month?", TODAY)
    assert phrase == "last month" and p.start.isoformat() == "2026-08-01"
    p, phrase = find_period_in_text("top merchants in august 2026", TODAY)
    assert p.end.isoformat() == "2026-08-31"
    p, phrase = find_period_in_text("transactions over 5000 in the last 14 days", TODAY)
    assert p.days == 14
    assert find_period_in_text("what are my biggest purchases", TODAY) is None
