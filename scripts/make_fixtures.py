#!/usr/bin/env python3
"""Generate synthetic ingestion fixtures: a bank CSV, a statement PDF, a receipt image and an SMS dump.

Deterministic content, so tests can assert exact numbers. Re-run any time: `python scripts/make_fixtures.py`.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures"

# date, narration, ref, withdrawal, deposit, balance
CSV_ROWS = [
    ("01/09/2026", "NEFT/SALARY/NORTHWIND TRADERS/SEP26", "N26091234", "", "1,05,000.00", "2,41,560.40"),
    ("02/09/2026", "UPI-MR VERMA-verma@okhdfcbank-HDFC0001234-425512345678-RENT SEP", "425512345678", "22,000.00", "", "2,19,560.40"),
    ("03/09/2026", "POS 4321XXXXXXXX9876 STARBUCKS COFFEE", "S2609031", "385.00", "", "2,19,175.40"),
    ("04/09/2026", "UPI/ZOMATO/425612345679/Order", "425612345679", "612.00", "", "2,18,563.40"),
    ("05/09/2026", "ACH/GROWW SIP/MF", "G2609050", "5,000.00", "", "2,13,563.40"),
    ("06/09/2026", "UPI/BLINKIT/425712345680/Grocery", "425712345680", "1,240.00", "", "2,12,323.40"),
    ("07/09/2026", "BBPS/TATA POWER/425812345681", "425812345681", "1,870.00", "", "2,10,453.40"),
    ("08/09/2026", "REFUND/MYNTRA/425912345682", "425912345682", "", "1,299.00", "2,11,752.40"),
    ("09/09/2026", "POS 4321XXXXXXXX9876 APOLLO PHARMACY", "S2609091", "463.50", "", "2,11,288.90"),
    ("10/09/2026", "UPI/UBER INDIA/426012345683/Trip", "426012345683", "218.00", "", "2,11,070.90"),
    ("11/09/2026", "IMPS/CC PAYMENT/426112345684", "426112345684", "14,320.00", "", "1,96,750.90"),
    ("12/09/2026", "INT.PD:426212345685", "426212345685", "", "312.40", "1,97,063.30"),
]
CSV_TOTAL_DEBIT = 22000 + 385 + 612 + 5000 + 1240 + 1870 + 463.50 + 218 + 14320
CSV_TOTAL_CREDIT = 105000 + 1299 + 312.40

SMS_MESSAGES = [
    "Rs.450.00 debited from a/c **4321 on 12-09-26 to VPA swiggy@ybl (UPI Ref No 426312345686). Not you? Call 18002586161 -HDFC Bank",
    "Dear Customer, Rs 1,200.00 debited from A/c X4321 on 11Sep26 to ZOMATO. Ref 426412345687. If not done by you, fwd this SMS to 9223008333 -SBI",
    "ICICI Bank Acct XX321 debited for Rs 350.00 on 10-Sep-26; BLUE TOKAI credited. UPI:426512345688. Call 18002662 for dispute. SMS BLOCK 321 to 9215676766.",
    "INR 599.00 spent on Axis Bank Card XX9876 at AIRTEL on 08-09-2026 12:10:44 IST. Avl Lmt INR 1,84,401.00. SMS BLOCK 9876 to 919951860002, if not done by you.",
    "Sent Rs.500.00 from Kotak Bank AC X4321 to rohan.k@okicici on 09-09-26. UPI Ref 426612345689. Not you? kotak.com/fraud",
    "Rs.95,000.00 credited to a/c **4321 on 01-09-26 by a/c linked to VPA acme.payroll@icici (UPI Ref No 426712345690) -HDFC Bank",
    "INR 42,000.00 credited to A/c XX4321 on 03/09/26 by NEFT from NORTHWIND LLC. Avl Bal INR 3,10,400.00 -Axis Bank",
    "Rs 4599.00 spent on HDFC Bank Card x9876 at CROMA on 2026-09-05:14:22:11. Avl bal: Rs 1,20,401.00. Not you? Call 18002586161",
    "Paid Rs.250 to Third Wave Coffee via UPI on 07-09-2026. Ref 426812345691. Powered by Google Pay.",
    "Your OTP for txn of Rs 2,499.00 at AMAZON is 482913. Valid for 10 mins. Do not share it with anyone. -HDFC Bank",
    "Get 10% cashback up to Rs 500 on your first order with code WELCOME10. Offer valid till 30 Sep. T&C apply. -Blinkit",
    "Rahul S has requested Rs 1,500.00 from you via UPI. Approve in your bank app. Ref 426912345692.",
    "Your a/c XX4321 balance as on 12-09-26 is Rs 1,97,063.30. -HDFC Bank",
    "Txn of Rs 899.00 at NETFLIX on Card XX9876 failed due to insufficient limit on 12-09-26. -Axis Bank",
]
SMS_EXPECTED_PARSED = 9
SMS_EXPECTED_SKIPPED = 5

RECEIPT_LINES = [
    "BLUE TOKAI COFFEE ROASTERS",
    "12th Main, Indiranagar, Bengaluru 560038",
    "GSTIN 29ABCDE1234F1Z5",
    "Date: 12/09/2026   Time: 09:41",
    "Bill No: 4471   Table: 6",
    "--------------------------------------",
    "Cappuccino            2 x 220.00   440.00",
    "Almond Croissant      1 x 180.00   180.00",
    "--------------------------------------",
    "Subtotal                           620.00",
    "CGST 2.5%                           15.50",
    "SGST 2.5%                           15.50",
    "GRAND TOTAL                        651.00",
    "Paid by UPI",
    "Thank you, visit again!",
]
RECEIPT_TOTAL = 651.00


def make_csv() -> Path:
    p = OUT / "statement_sample.csv"
    lines = ["Account Statement", "Account No: XXXXXXXX4321", "Period: 01/09/2026 to 12/09/2026", "",
             "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance"]
    for d, n, r, w, c, b in CSV_ROWS:
        lines.append(f'{d},"{n}",{r},{d},"{w}","{c}","{b}"')
    lines += ["", "STATEMENT SUMMARY :-", "Opening Balance,Dr Count,Cr Count,Debits,Credits,Closing Bal"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def make_pdf() -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    p = OUT / "statement_sample.pdf"
    doc = SimpleDocTemplate(str(p), pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    styles = getSampleStyleSheet()
    body = [Paragraph("Sample Bank Ltd - Account Statement", styles["Title"]),
            Paragraph("Account No: XXXXXXXX4321 &nbsp;&nbsp; Period: 01/09/2026 to 12/09/2026 &nbsp;&nbsp; Currency: INR", styles["Normal"]),
            Spacer(1, 6 * mm)]
    data = [["Date", "Narration", "Ref No", "Withdrawal", "Deposit", "Balance"]]
    for d, n, r, w, c, b in CSV_ROWS:
        data.append([d, n if len(n) < 46 else n[:44] + "..", r, w, c, b])
    t = Table(data, colWidths=[20 * mm, 78 * mm, 24 * mm, 22 * mm, 22 * mm, 24 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    body.append(t)
    body.append(Spacer(1, 6 * mm))
    body.append(Paragraph("This is a computer generated statement and does not require a signature.", styles["Italic"]))
    doc.build(body)
    return p


def make_receipt() -> Path:
    from PIL import Image, ImageDraw, ImageFont

    p = OUT / "receipt_sample.png"
    font_path = "/System/Library/Fonts/Supplemental/Courier New.ttf"
    try:
        font = ImageFont.truetype(font_path, 26)
        bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Courier New Bold.ttf", 30)
    except OSError:
        font = bold = ImageFont.load_default()
    w, line_h, pad = 900, 40, 40
    img = Image.new("RGB", (w, pad * 2 + line_h * len(RECEIPT_LINES)), "white")
    d = ImageDraw.Draw(img)
    y = pad
    for i, line in enumerate(RECEIPT_LINES):
        d.text((pad, y), line, font=bold if i == 0 or line.startswith("GRAND TOTAL") else font, fill="black")
        y += line_h
    img.save(p)
    return p


def make_sms() -> Path:
    p = OUT / "sms_sample.txt"
    p.write_text("\n\n".join(SMS_MESSAGES) + "\n", encoding="utf-8")
    return p


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for fn in (make_csv, make_pdf, make_receipt, make_sms):
        print("wrote", fn().relative_to(ROOT))


if __name__ == "__main__":
    main()
