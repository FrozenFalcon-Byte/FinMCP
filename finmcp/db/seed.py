"""Deterministic, realistic demo data: ~90 days of an Indian salaried professional's transactions."""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from ..taxonomy import seed_categories
from .repository import Repository, fingerprint_for

# (day_of_month, merchant, description template, amount or (lo, hi), direction)
RECURRING: list[tuple[int, str, str, Any, str]] = [
    (1, "ACME TECHNOLOGIES PVT LTD", "NEFT/SALARY/ACME TECH/{mon}{yy}", 95000, "credit"),
    (2, "RENT - MR SHARMA", "UPI/P2A/{ref}/RENT {mon}", 25000, "debit"),
    (3, "CULT.FIT", "UPI/CULTFIT/{ref}/Membership", 1500, "debit"),
    (5, "ZERODHA COIN SIP", "ACH/ZERODHA BROKING/SIP", 10000, "debit"),
    (8, "AIRTEL POSTPAID", "BBPS/AIRTEL/{ref}/Mobile bill", 599, "debit"),
    (10, "ACT FIBERNET", "UPI/ACTFIBERNET/{ref}/Broadband", 999, "debit"),
    (12, "NETFLIX", "POS 4321XXXXXXXX9876 NETFLIX.COM", 649, "debit"),
    (15, "BESCOM ELECTRICITY", "BBPS/BESCOM/{ref}", (1100, 2600), "debit"),
    (18, "GOOGLE ONE", "POS GOOGLE*GOOGLE ONE", 130, "debit"),
    (20, "SPOTIFY", "POS 4321XXXXXXXX9876 SPOTIFY", 119, "debit"),
    (22, "LIC OF INDIA", "ACH/LIC PREMIUM/{ref}", 2150, "debit"),
    (28, "HDFC CREDIT CARD PAYMENT", "IMPS/CC PAYMENT/{ref}", (8000, 22000), "debit"),
]

# (expected per week, [(merchant, description template)], (lo, hi), direction, weekend_boost)
POOLS: list[tuple[float, list[tuple[str, str]], tuple[int, int], str, float]] = [
    (4.0, [("SWIGGY", "UPI/SWIGGY/{ref}/Food order"), ("ZOMATO", "UPI/ZOMATO/{ref}/Order"),
           ("DOMINOS PIZZA", "POS DOMINOS PIZZA IND"), ("BIRYANI BY KILO", "UPI/BBK/{ref}")], (180, 720), "debit", 1.6),
    (3.0, [("BLINKIT", "UPI/BLINKIT/{ref}/Grocery"), ("ZEPTO", "UPI/ZEPTO/{ref}"), ("BIGBASKET", "POS BIGBASKET"),
           ("DMART", "POS AVENUE SUPERMARTS")], (240, 1900), "debit", 1.3),
    (5.0, [("UBER", "UPI/UBER INDIA/{ref}/Trip"), ("OLA CABS", "UPI/OLA/{ref}"), ("RAPIDO", "UPI/RAPIDO/{ref}"),
           ("BMRCL METRO", "UPI/BMRCL/{ref}/Metro")], (35, 480), "debit", 0.7),
    (2.0, [("STARBUCKS", "POS STARBUCKS COFFEE"), ("THIRD WAVE COFFEE", "UPI/THIRDWAVE/{ref}"),
           ("BLUE TOKAI", "UPI/BLUETOKAI/{ref}")], (180, 460), "debit", 1.2),
    (1.0, [("AMAZON", "POS AMAZON PAY INDIA"), ("FLIPKART", "UPI/FLIPKART/{ref}"), ("MYNTRA", "UPI/MYNTRA/{ref}"),
           ("DECATHLON", "POS DECATHLON SPORTS")], (399, 5200), "debit", 1.5),
    (0.5, [("APOLLO PHARMACY", "POS APOLLO PHARMACY"), ("TATA 1MG", "UPI/1MG/{ref}"),
           ("PRACTO", "UPI/PRACTO/{ref}/Consult")], (150, 950), "debit", 1.0),
    (0.5, [("BOOKMYSHOW", "UPI/BOOKMYSHOW/{ref}"), ("PVR INOX", "POS PVR INOX LTD")], (350, 980), "debit", 2.0),
    (0.5, [("HP PETROL PUMP", "POS HP PETROL PUMP"), ("INDIAN OIL", "UPI/IOCL/{ref}/Fuel")], (1500, 3200), "debit", 1.0),
    (0.7, [("ROHAN K", "UPI/P2P/{ref}/Dinner split"), ("PRIYA M", "UPI/P2P/{ref}"),
           ("AMIT S", "UPI/P2P/{ref}/Trip share")], (300, 3000), "debit", 1.4),
    (0.4, [("AMAZON REFUND", "REFUND AMAZON PAY"), ("CRED CASHBACK", "CASHBACK/CRED/{ref}"),
           ("HDFC BANK INTEREST", "INT.PD:{ref}")], (45, 800), "credit", 1.0),
    (0.25, [("URBAN COMPANY", "UPI/URBANCOMPANY/{ref}/Salon"), ("TRUEFITT & HILL", "POS TRUEFITT HILL")], (350, 1200), "debit", 1.5),
    (0.3, [("UDEMY", "POS UDEMY"), ("AMAZON KINDLE", "POS AMAZON KINDLE")], (399, 1299), "debit", 1.0),
    # Deliberately opaque merchants: rules cannot categorize these, so they land in the review queue.
    (0.35, [("PAYTM*QR MERCHANT 8827", "UPI/PAYTMQR{ref}"), ("BHARATPE MERCHANT 22", "UPI/BHARATPE/{ref}"),
            ("RAZORPAY*ACME", "POS RAZORPAY ACME")], (80, 900), "debit", 1.0),
]

# (days before end, merchant, description, amount, direction)
ONE_OFFS: list[tuple[int, str, str, float, str]] = [
    (34, "INDIGO", "POS INTERGLOBE AVIATION", 6840, "debit"),
    (31, "OYO ROOMS", "UPI/OYO/{ref}", 2799, "debit"),
    (12, "CROMA", "POS CROMA A TATA ENT", 4599, "debit"),
    (50, "GIVEINDIA", "UPI/GIVEINDIA/{ref}/Donation", 1000, "debit"),
    (26, "HDFC BANK", "SMS CHARGES QTR", 17.7, "debit"),
    (44, "FREELANCE - NORTHWIND LLC", "SWIFT/INWARD/NORTHWIND", 42000, "credit"),
]

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _fmt(template: str, d: date, rng: random.Random) -> str:
    return template.format(ref=f"{rng.randrange(10**11, 10**12)}", mon=MONTHS[d.month - 1], yy=str(d.year)[2:])


def seed_demo_data(repo: Repository, *, days: int = 90, end: date | None = None, rng_seed: int = 42, categorize: bool = True) -> dict[str, int]:
    """Populate categories and ~days of transactions. Idempotent thanks to fingerprints."""
    from ..llm.provider import RuleBasedProvider
    from ..services.categorize import Categorizer  # local import: avoids a cycle at import time

    seed_categories(repo)
    rng = random.Random(rng_seed)
    end = end or date.today()
    start = end - timedelta(days=days - 1)
    rows: list[dict[str, Any]] = []

    d = start
    while d <= end:
        for dom, merchant, tpl, amount, direction in RECURRING:
            if d.day == dom:
                amt = rng.randint(*amount) if isinstance(amount, tuple) else amount
                rows.append(dict(date=d, merchant=merchant, description=_fmt(tpl, d, rng), amount=float(amt), direction=direction))
        weekend = d.weekday() >= 5
        for rate, merchants, (lo, hi), direction, boost in POOLS:
            p = rate / 7 * (boost if weekend else 1.0)
            n = 0
            while p > 0 and rng.random() < p:
                n += 1
                p -= 1.0 if p >= 1 else p
                if n >= 3:
                    break
            for _ in range(n):
                merchant, tpl = rng.choice(merchants)
                amt = rng.randint(lo, hi)
                amt = round(amt / 5) * 5 if amt > 100 else amt
                rows.append(dict(date=d, merchant=merchant, description=_fmt(tpl, d, rng), amount=float(amt), direction=direction))
        d += timedelta(days=1)

    for days_ago, merchant, tpl, amount, direction in ONE_OFFS:
        dd = end - timedelta(days=days_ago)
        if dd >= start:
            rows.append(dict(date=dd, merchant=merchant, description=_fmt(tpl, dd, rng), amount=float(amount), direction=direction))

    inserted = 0
    duplicates = 0
    new_ids: list[int] = []
    for r in sorted(rows, key=lambda x: x["date"]):
        iso = r["date"].isoformat()
        raw = f"{iso} {r['description']} {'CR' if r['direction'] == 'credit' else 'DR'} {r['amount']:.2f}"
        tx = repo.insert_transaction(
            date=iso, amount=r["amount"], merchant=r["merchant"], direction=r["direction"], description=r["description"],
            source="seed", raw_text=raw, fingerprint=fingerprint_for(iso, r["amount"], r["direction"], r["merchant"], raw),
            ignore_duplicate=True,
        )
        if tx is None:
            duplicates += 1
        else:
            inserted += 1
            new_ids.append(tx.id)

    categorized = 0
    if categorize and new_ids:
        cat = Categorizer(repo, RuleBasedProvider(), actor="seed")
        for tx_id in new_ids:
            result = cat.categorize(tx_id)
            if result["category"]:
                categorized += 1
    repo.audit("seed", "seed_demo_data", detail={"inserted": inserted, "duplicates": duplicates, "categorized": categorized})
    return {"inserted": inserted, "duplicates": duplicates, "categorized": categorized, "categories": len(repo.list_categories())}
