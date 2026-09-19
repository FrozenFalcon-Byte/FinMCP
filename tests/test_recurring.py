from datetime import date, timedelta

from finmcp.services.recurring import detect_recurring, list_recurring

TODAY = date(2026, 9, 17)


def rows(merchant: str, dates: list[date], amounts: list[float], category: str = "Subscriptions", kind: str = "expense"):
    return [{"id": i, "date": d.isoformat(), "amount": a, "merchant": merchant, "category": category, "category_kind": kind}
            for i, (d, a) in enumerate(zip(dates, amounts, strict=False), start=1)]


def test_monthly_subscription_detected():
    dates = [date(2026, m, 12) for m in (5, 6, 7, 8, 9)]
    found = detect_recurring(rows("NETFLIX", dates, [649] * 5), TODAY)
    assert len(found) == 1
    n = found[0]
    assert n["cadence"] == "monthly" and n["amount"] == 649 and n["next_due"] == "2026-10-12" and n["status"] == "upcoming"
    assert not n["amount_varies"] and n["occurrences"] == 5 and abs(n["monthly_cost"] - 649 * 30.4375 / 30) < 1


def test_variable_bill_is_still_a_bill():
    dates = [date(2026, m, 15) for m in (6, 7, 8, 9)]
    found = detect_recurring(rows("BESCOM ELECTRICITY", dates, [1100, 2400, 1700, 2600], "Utilities"), TODAY)
    assert len(found) == 1 and found[0]["amount_varies"] and found[0]["cadence"] == "monthly"


def test_irregular_food_orders_are_not_recurring():
    dates = [TODAY - timedelta(days=d) for d in (1, 2, 4, 5, 9, 10, 11, 15, 20)]
    assert detect_recurring(rows("SWIGGY", dates, [180, 420, 250, 610, 320, 200, 450, 380, 260], "Food & Dining"), TODAY) == []


def test_weekly_needs_stable_amount():
    dates = [TODAY - timedelta(days=7 * k) for k in range(6)]
    assert detect_recurring(rows("BLINKIT", dates, [900, 1400, 600, 1900, 800, 1200], "Groceries"), TODAY) == []
    plan = detect_recurring(rows("WEEKLY PLAN", dates, [99] * 6), TODAY)
    assert len(plan) == 1 and plan[0]["cadence"] == "weekly"


def test_cancelled_subscription_drops_out():
    dates = [date(2026, m, 3) for m in (2, 3, 4, 5)]  # last paid in May; two cycles missed by September
    assert detect_recurring(rows("OLD GYM", dates, [1500] * 4, "Personal Care"), TODAY) == []


def test_due_and_overdue_status():
    due = detect_recurring(rows("SPOTIFY", [date(2026, m, 18) for m in (6, 7, 8)], [119] * 3), TODAY)[0]
    assert due["status"] == "due" and due["days_until"] == 1
    late = detect_recurring(rows("AIRTEL", [date(2026, m, 8) for m in (6, 7, 8)], [599] * 3, "Utilities"), TODAY)[0]
    assert late["status"] == "overdue" and late["days_until"] < -2


def test_list_recurring_on_seeded_ledger(seeded_repo):
    out = list_recurring(seeded_repo, TODAY)
    names = {i["merchant"] for i in out["items"]}
    assert {"NETFLIX", "SPOTIFY", "RENT - MR SHARMA", "ZERODHA COIN SIP", "LIC OF INDIA"} <= names
    assert "SWIGGY" not in names and "UBER" not in names
    sip = next(i for i in out["items"] if i["merchant"] == "ZERODHA COIN SIP")
    assert sip["category_kind"] == "transfer"
    assert out["monthly_total"] > out["monthly_expenses"] > 0
    assert all(-2 <= u["days_until"] <= 14 for u in out["upcoming"])
