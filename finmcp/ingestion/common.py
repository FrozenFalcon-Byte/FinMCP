"""Shared parsing helpers: dates, amounts, merchant extraction from bank narrations."""
from __future__ import annotations

import re
from datetime import datetime

DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d",
    "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %b %y", "%d%b%y", "%d%b%Y", "%d %B %Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y",
    "%d %b, %Y", "%Y%m%d",
)

_DATE_TOKEN = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[ \-]?[A-Za-z]{3,9}[ \-,]*\d{2,4}|[A-Za-z]{3,9} \d{1,2}, \d{4})"
)


def parse_date(text: str | None) -> str | None:
    """Parse the many date spellings banks use into ISO. Returns None when nothing parses."""
    if not text:
        return None
    t = text.strip()
    # drop a trailing time component
    t = re.sub(r"[ T:]\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm|ist))?$", "", t, flags=re.IGNORECASE).strip()
    candidates = [t]
    m = re.match(r"^(\d{1,2})([A-Za-z]{3,9})(\d{2,4})$", t)  # 12Sep26
    if m:
        candidates.append(f"{m.group(1)} {m.group(2).title()} {m.group(3)}")
    candidates.append(re.sub(r"([A-Za-z]{3,9})", lambda mm: mm.group(1).title(), t))
    for cand in candidates:
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(cand, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def find_date(text: str) -> str | None:
    for m in _DATE_TOKEN.finditer(text):
        iso = parse_date(m.group(1))
        if iso:
            return iso
    return None


_AMOUNT = re.compile(r"(?:(?:rs|inr|₹|rupees)\.?\s*)?(\(?-?\d[\d,]*(?:\.\d{1,2})?\)?)(\s*(?:dr|cr))?", re.IGNORECASE)


def parse_amount(text: str | None) -> float | None:
    if text is None:
        return None
    t = str(text).strip()
    if not t or t in {"-", "--", "NA", "n/a"}:
        return None
    m = re.search(r"\(?-?\d[\d,]*(?:\.\d{1,2})?\)?", t)
    if not m:
        return None
    raw = m.group(0)
    neg = raw.startswith("(") or raw.startswith("-")
    num = raw.strip("()-").replace(",", "")
    try:
        v = float(num)
    except ValueError:
        return None
    return -v if neg else v


CHANNELS = {"UPI", "POS", "NEFT", "IMPS", "ACH", "BBPS", "RTGS", "ATM", "ECOM", "NACH", "EMI", "CHQ", "MB", "IB", "NET",
            "NFS", "VPS", "TPT", "FT", "IMPS-OUT", "IMPS-IN", "NEFT-OUT", "NEFT-IN", "UPI-OUT", "UPI-IN", "ME", "DC", "CC"}
PURPOSE_WORDS = {"SALARY", "RENT", "SIP", "PAYMENT", "TRANSFER", "P2P", "P2A", "P2M", "CR", "DR", "CASHBACK", "REFUND",
                 "PURCHASE", "BILLPAY", "BILL", "RECHARGE", "AUTOPAY", "MANDATE", "INWARD", "OUTWARD", "SWIFT"}
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_MASKED = re.compile(r"\b[\dXx*]{6,}\b")


def merchant_from_narration(narration: str) -> str:
    """Pull the counterparty out of a bank narration.

    'UPI/SWIGGY/412345678901/Food order' -> 'SWIGGY'
    'UPI-ROHAN K-rohank@okicici-HDFC0001234-4123-Dinner' -> 'ROHAN K'
    'POS 4321XXXXXXXX9876 NETFLIX.COM' -> 'NETFLIX.COM'
    'NEFT/SALARY/ACME TECH/SEP26' -> 'ACME TECH'
    """
    s = re.sub(r"\s+", " ", narration or "").strip()
    if not s:
        return "UNKNOWN"
    if "/" in s or "|" in s:
        parts = [p.strip() for p in re.split(r"[/|]+", s) if p.strip()]
    elif s.count("-") >= 3:
        parts = [p.strip() for p in s.split("-") if p.strip()]
    else:
        parts = [s]

    def usable(p: str) -> bool:
        up = p.upper()
        if "@" in p or _IFSC.match(p.replace(" ", "")):
            return False
        if not re.search(r"[A-Za-z]{2,}", p):
            return False
        if re.fullmatch(r"(?i)(ref|utr|txn|rrn)\s*(no\.?)?\s*[:#]?\s*\w*", p):
            return False
        return up not in CHANNELS

    if len(parts) > 1:
        strong = [p for p in parts if usable(p) and p.upper() not in PURPOSE_WORDS]
        weak = [p for p in parts if usable(p)]
        cand = strong[0] if strong else weak[0] if weak else parts[0]
    else:
        cand = parts[0]
        cand = re.sub(r"^(?:POS|ECOM|ATM|UPI|NEFT|IMPS|RTGS|ACH|BBPS|NACH)\b[\s:\-]*", "", cand, flags=re.IGNORECASE)
    cand = _MASKED.sub(" ", cand)
    cand = re.sub(r"\b(?:ref|utr|txn|rrn)\s*(?:no\.?)?\s*[:#]?\s*\w+", " ", cand, flags=re.IGNORECASE)
    cand = re.sub(r"\s+", " ", cand).strip(" -:.,*#")
    return (cand or s)[:80]


def clean_text(s: str | None) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s or None
