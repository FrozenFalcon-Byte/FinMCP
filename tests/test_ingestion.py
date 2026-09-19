import shutil
from pathlib import Path

import pytest

from finmcp.ingestion import Importer, detect_kind
from finmcp.ingestion.common import merchant_from_narration, parse_amount, parse_date
from finmcp.ingestion.receipts import parse_receipt, parse_receipt_text
from finmcp.ingestion.sms import parse_sms, parse_sms_dump
from finmcp.ingestion.statements import parse_csv, parse_csv_text, parse_pdf
from finmcp.llm.provider import RuleBasedProvider
from finmcp.services.categorize import Categorizer
from tests.conftest import connect, result_data, result_text

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CSV_DEBIT_TOTAL = 22000 + 385 + 612 + 5000 + 1240 + 1870 + 463.50 + 218 + 14320
CSV_CREDIT_TOTAL = 105000 + 1299 + 312.40


@pytest.mark.parametrize("text,iso", [
    ("2026-09-12", "2026-09-12"), ("12/09/2026", "2026-09-12"), ("12-09-26", "2026-09-12"), ("12Sep26", "2026-09-12"),
    ("12-Sep-2026", "2026-09-12"), ("12 Sep 2026", "2026-09-12"), ("Sep 12, 2026", "2026-09-12"), ("2026-09-05:14:22:11", "2026-09-05"),
    ("08-09-2026 12:10:44 IST", "2026-09-08"), ("garbage", None), ("", None),
])
def test_parse_date(text, iso):
    assert parse_date(text) == iso


def test_parse_amount():
    assert parse_amount("1,05,000.00") == 105000.0
    assert parse_amount("Rs. 385") == 385.0
    assert parse_amount("(463.50)") == -463.5
    assert parse_amount("-") is None and parse_amount("") is None


@pytest.mark.parametrize("narration,merchant", [
    ("UPI/SWIGGY/412345678901/Food order", "SWIGGY"),
    ("UPI-ROHAN K-rohank@okicici-HDFC0001234-4123-Dinner", "ROHAN K"),
    ("POS 4321XXXXXXXX9876 NETFLIX.COM", "NETFLIX.COM"),
    ("NEFT/SALARY/ACME TECH/SEP26", "ACME TECH"),
    ("ACH/ZERODHA BROKING/SIP", "ZERODHA BROKING"),
    ("IMPS/CC PAYMENT/123", "CC PAYMENT"),
    ("BBPS/BESCOM/123", "BESCOM"),
    ("POS AVENUE SUPERMARTS", "AVENUE SUPERMARTS"),
    ("CASHBACK/CRED/412", "CRED"),
])
def test_merchant_from_narration(narration, merchant):
    assert merchant_from_narration(narration) == merchant


def test_csv_fixture():
    r = parse_csv(FIXTURES / "statement_sample.csv")
    assert r.parser == "csv" and r.count == 12 and not r.warnings
    debits = sum(t.amount for t in r.transactions if t.direction == "debit")
    credits = sum(t.amount for t in r.transactions if t.direction == "credit")
    assert abs(debits - CSV_DEBIT_TOTAL) < 0.01 and abs(credits - CSV_CREDIT_TOTAL) < 0.01
    first = r.transactions[0]
    assert first.date == "2026-09-01" and first.merchant == "NORTHWIND TRADERS" and first.direction == "credit"
    assert first.balance_after == 241560.40 and first.reference == "N26091234"
    rent = r.transactions[1]
    assert rent.merchant == "MR VERMA" and rent.amount == 22000


def test_csv_single_amount_column_with_type():
    text = "date,description,amount,type\n2026-09-01,Salary ACME,95000,CR\n2026-09-02,UPI/SWIGGY/1/Food,450,DR\n2026-09-03,POS AMAZON,-1200,\n"
    r = parse_csv_text(text)
    assert [(t.direction, t.amount) for t in r.transactions] == [("credit", 95000.0), ("debit", 450.0), ("credit", 1200.0)]


def test_csv_without_header():
    r = parse_csv_text("hello,world\n1,2\n")
    assert r.count == 0 and r.warnings


def test_pdf_fixture():
    r = parse_pdf(FIXTURES / "statement_sample.pdf")
    assert r.parser == "pdfplumber-tables" and r.count == 12, (r.parser, r.warnings)
    assert sum(t.amount for t in r.transactions if t.direction == "credit") == pytest.approx(CSV_CREDIT_TOTAL, abs=0.01)
    assert {t.direction for t in r.transactions} == {"debit", "credit"}


def test_sms_formats():
    tx, why = parse_sms("Rs.450.00 debited from a/c **4321 on 12-09-26 to VPA swiggy@ybl (UPI Ref No 426312345686). -HDFC Bank")
    assert tx and tx.amount == 450 and tx.direction == "debit" and tx.date == "2026-09-12" and tx.merchant.lower() == "swiggy"
    tx, _ = parse_sms("ICICI Bank Acct XX321 debited for Rs 350.00 on 10-Sep-26; BLUE TOKAI credited. UPI:426512345688.")
    assert tx and tx.direction == "debit" and tx.merchant == "BLUE TOKAI" and tx.date == "2026-09-10"
    tx, _ = parse_sms("INR 599.00 spent on Axis Bank Card XX9876 at AIRTEL on 08-09-2026 12:10:44 IST. Avl Lmt INR 1,84,401.00.")
    assert tx and tx.amount == 599 and tx.merchant == "AIRTEL" and tx.date == "2026-09-08"
    tx, _ = parse_sms("Rs.95,000.00 credited to a/c **4321 on 01-09-26 by a/c linked to VPA acme.payroll@icici (UPI Ref No 4267) -HDFC Bank")
    assert tx and tx.direction == "credit" and tx.amount == 95000 and "acme" in tx.merchant.lower()
    tx, _ = parse_sms("INR 42,000.00 credited to A/c XX4321 on 03/09/26 by NEFT from NORTHWIND LLC. Avl Bal INR 3,10,400.00 -Axis Bank")
    assert tx and tx.direction == "credit" and tx.amount == 42000 and tx.merchant == "NORTHWIND LLC"
    tx, _ = parse_sms("Paid Rs.250 to Third Wave Coffee via UPI on 07-09-2026. Ref 426812345691.")
    assert tx and tx.amount == 250 and tx.merchant == "Third Wave Coffee" and tx.date == "2026-09-07"
    tx, _ = parse_sms("Rs 4599.00 spent on HDFC Bank Card x9876 at CROMA on 2026-09-05:14:22:11. Avl bal: Rs 1,20,401.00.")
    assert tx and tx.merchant == "CROMA" and tx.date == "2026-09-05" and tx.amount == 4599
    for noise, reason in [
        ("Your OTP for txn of Rs 2,499.00 at AMAZON is 482913. Valid for 10 mins.", "otp"),
        ("Get 10% cashback up to Rs 500 on your first order with code WELCOME10. T&C apply.", "promotion"),
        ("Rahul S has requested Rs 1,500.00 from you via UPI.", "payment request"),
        ("Your a/c XX4321 balance as on 12-09-26 is Rs 1,97,063.30.", "no debit/credit keyword"),
        ("Txn of Rs 899.00 at NETFLIX on Card XX9876 failed due to insufficient limit.", "failed transaction"),
    ]:
        tx, why = parse_sms(noise)
        assert tx is None and why == reason, (noise, why)


def test_sms_dump_fixture():
    r = parse_sms_dump((FIXTURES / "sms_sample.txt").read_text())
    assert r.count == 9 and len(r.skipped) == 5, (r.count, r.skipped)
    assert sum(t.amount for t in r.transactions if t.direction == "credit") == 95000 + 42000
    assert all(t.source == "sms" for t in r.transactions)


def test_receipt_text_heuristics():
    text = "\n".join([
        "BLUE TOKAI COFFEE ROASTERS", "12th Main, Indiranagar", "GSTIN 29ABCDE1234F1Z5", "Date: 12/09/2026 Time: 09:41", "Bill No: 4471",
        "Cappuccino 2 x 220.00 440.00", "Almond Croissant 1 x 180.00 180.00", "Subtotal 620.00", "CGST 2.5% 15.50", "SGST 2.5% 15.50",
        "GRAND TOTAL 651.00", "Paid by UPI", "Thank you, visit again!",
    ])
    r = parse_receipt_text(text)
    tx = r.transactions[0]
    assert tx.merchant == "BLUE TOKAI COFFEE ROASTERS" and tx.date == "2026-09-12" and tx.amount == 651.0
    assert [(i.name, i.quantity, i.total) for i in tx.line_items] == [("Cappuccino", 2.0, 440.0), ("Almond Croissant", 1.0, 180.0)]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_receipt_image_ocr():
    r = parse_receipt(FIXTURES / "receipt_sample.png")
    assert r.parser == "tesseract+heuristics" and r.count == 1
    tx = r.transactions[0]
    assert tx.amount == 651.0 and tx.date == "2026-09-12" and "BLUE TOKAI" in tx.merchant.upper()


def test_detect_kind():
    assert detect_kind("a.pdf") == "statement" and detect_kind("a.CSV") == "csv" and detect_kind("a.jpg") == "receipt" and detect_kind("a.txt") == "sms"
    with pytest.raises(ValueError):
        detect_kind("a.xyz")


def test_importer_dedupe_and_categorize(repo):
    imp = Importer(repo, Categorizer(repo, RuleBasedProvider()), RuleBasedProvider())
    preview = imp.import_file(FIXTURES / "statement_sample.csv", dry_run=True)
    assert preview["dry_run"] and preview["parsed"] == 12 and preview["new"] == 12 and preview["duplicates"] == 0
    assert repo.count_transactions() == 0
    report = imp.import_file(FIXTURES / "statement_sample.csv")
    assert report["inserted"] == 12 and report["duplicates"] == 0 and report["categorized"] >= 10
    cats = {t["merchant"]: t["category"] for t in report["transactions"]}
    assert cats["ZOMATO"] == "Food & Dining" and cats["BLINKIT"] == "Groceries" and cats["NORTHWIND TRADERS"] == "Income"
    again = imp.import_file(FIXTURES / "statement_sample.csv")
    assert again["inserted"] == 0 and again["duplicates"] == 12
    assert repo.count_transactions() == 12
    sms = imp.import_text((FIXTURES / "sms_sample.txt").read_text(), kind="sms", source_name="phone")
    assert sms["inserted"] == 9 and sms["parsed"] == 9
    assert len(repo.recent_imports()) == 3  # dry run is not recorded
    with pytest.raises(ValueError):
        imp.import_file(FIXTURES / "does_not_exist.csv")


async def test_server_ingestion_tools(server):
    async with connect(server) as client:
        r = await client.call_tool("parse_statement", {"file_path": str(FIXTURES / "statement_sample.pdf")})
        assert not r.is_error, result_text(r)
        data = result_data(r)
        assert data["parsed"] == 12 and data["parser"] == "pdfplumber-tables"
        r = await client.call_tool("import_statement", {"file_path": str(FIXTURES / "statement_sample.csv"), "dry_run": True})
        assert result_data(r)["dry_run"] is True
        r = await client.call_tool("import_statement", {"file_path": str(FIXTURES / "statement_sample.csv")})
        data = result_data(r)
        assert data["inserted"] == 12 and data["import_id"]
        r = await client.call_tool("import_text", {"text": "Rs.450.00 debited from a/c **4321 on 12-09-26 to VPA swiggy@ybl (UPI Ref No 1). -HDFC Bank\n\nYour OTP is 123456 for txn of Rs 10", "kind": "sms"})
        data = result_data(r)
        assert data["inserted"] == 1 and data["transactions"][0]["category"] == "Food & Dining" and len(data["skipped"]) == 1
        r = await client.call_tool("import_statement", {"file_path": "/nope/missing.csv"})
        assert r.is_error and "not found" in result_text(r)
        res = await client.read_resource("finmcp://imports/recent")
        assert "statement_sample.csv" in res.contents[0].text
