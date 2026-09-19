import pytest

from finmcp.llm.provider import RuleBasedProvider
from finmcp.services.categorize import Categorizer
from finmcp.taxonomy import match_keywords, resolve_category_name


@pytest.mark.parametrize("text,expected", [
    ("SWIGGY UPI/SWIGGY/4123/Food order", "Food & Dining"),
    ("BLINKIT", "Groceries"),
    ("POS AVENUE SUPERMARTS", "Groceries"),
    ("UPI/UBER INDIA/1/Trip", "Transport"),
    ("HP PETROL PUMP", "Transport"),
    ("NETFLIX POS 4321 NETFLIX.COM", "Entertainment"),
    ("BESCOM ELECTRICITY BBPS/BESCOM/1", "Utilities"),
    ("ZERODHA COIN SIP ACH/ZERODHA BROKING/SIP", "Investments"),
    ("HDFC CREDIT CARD PAYMENT IMPS/CC PAYMENT/1", "Transfers"),
    ("ROHAN K UPI/P2P/1/Dinner split", "Transfers"),
    ("LIC OF INDIA ACH/LIC PREMIUM", "Insurance"),
    ("CULT.FIT Membership", "Personal Care"),
    ("INDIGO POS INTERGLOBE AVIATION", "Travel"),
])
def test_keyword_rules(text, expected):
    hit = match_keywords(text)
    assert hit and hit[0] == expected


def test_keyword_no_match():
    assert match_keywords("PAYTM*QR MERCHANT 8827 UPI/PAYTMQR1") is None


def test_resolve_category_name():
    assert resolve_category_name("food") == "Food & Dining"
    assert resolve_category_name("Groceries") == "Groceries"
    assert resolve_category_name("food and dining") == "Food & Dining"
    assert resolve_category_name("nonsense") is None


def test_pipeline_rules_and_memory(repo):
    cat = Categorizer(repo, RuleBasedProvider(), actor="test")
    tx = repo.insert_transaction(date="2026-09-10", amount=420, merchant="SWIGGY", description="UPI/SWIGGY/1/Food order")
    r = cat.categorize(tx.id)
    assert r["category"] == "Food & Dining" and r["source"] == "rule" and r["confidence"] >= 0.8 and not r["needs_review"]

    unknown = repo.insert_transaction(date="2026-09-11", amount=80, merchant="PAYTM*QR MERCHANT 8827", description="UPI/PAYTMQR1")
    r = cat.categorize(unknown.id)
    assert r["category"] is None and r["needs_review"] is True

    # user files it -> memory learns -> next one from the same merchant is categorized with high confidence
    r = cat.apply_user_category(unknown.id, "groceries")
    assert r["category"] == "Groceries" and r["source"] == "user" and r["confidence"] == 1.0
    again = repo.insert_transaction(date="2026-09-12", amount=120, merchant="PAYTM*QR MERCHANT 8827")
    r = cat.categorize(again.id)
    assert r["category"] == "Groceries" and r["source"] == "memory" and r["confidence"] >= 0.85

    # user-set categories are not overwritten unless forced
    r = cat.categorize(unknown.id)
    assert r["changed"] is False and r["category"] == "Groceries"
    r = cat.categorize(unknown.id, force=True)
    assert r["category"] == "Groceries"  # memory still wins


def test_credit_becomes_income(repo):
    cat = Categorizer(repo, RuleBasedProvider())
    tx = repo.insert_transaction(date="2026-09-01", amount=95000, merchant="ACME TECHNOLOGIES", description="NEFT/SALARY/ACME", direction="credit")
    assert cat.categorize(tx.id)["category"] == "Income"
    refund = repo.insert_transaction(date="2026-09-02", amount=500, merchant="AMAZON", description="REFUND", direction="credit")
    assert cat.categorize(refund.id)["category"] == "Income"


def test_unknown_category_rejected(repo):
    cat = Categorizer(repo, RuleBasedProvider())
    tx = repo.insert_transaction(date="2026-09-01", amount=5, merchant="x")
    with pytest.raises(ValueError):
        cat.apply_user_category(tx.id, "Space Travel")
