"""Turn human period strings ('last month', '2026-08', 'last 30 days') into inclusive date ranges."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTH_NAMES.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTH_NAMES["sept"] = 9


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict[str, str | int]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label, "days": self.days}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def resolve_period(period: str | None, today: date | None = None) -> Period:
    """Resolve a period expression. Unknown expressions raise ValueError."""
    today = today or date.today()
    p = (period or "this month").strip().lower().replace("_", " ")
    p = re.sub(r"\s+", " ", p)

    # explicit ranges: 2026-08-01..2026-08-31 | 2026-08-01 to 2026-08-31 | from X to Y
    m = re.match(r"^(?:from )?(\d{4}-\d{2}-\d{2})\s*(?:\.\.|to|-|until|through)\s*(\d{4}-\d{2}-\d{2})$", p)
    if m:
        s, e = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
        if e < s:
            s, e = e, s
        return Period(s, e, f"{s.isoformat()} to {e.isoformat()}")
    m = re.match(r"^(\d{4})-(\d{2})$", p)
    if m:
        s, e = month_bounds(int(m.group(1)), int(m.group(2)))
        return Period(s, e, s.strftime("%B %Y"))
    m = re.match(r"^(\d{4})$", p)
    if m:
        y = int(m.group(1))
        return Period(date(y, 1, 1), date(y, 12, 31), str(y))
    m = re.match(r"^(\d{4}-\d{2}-\d{2})$", p)
    if m:
        d = date.fromisoformat(m.group(1))
        return Period(d, d, d.isoformat())

    if p in {"today"}:
        return Period(today, today, "today")
    if p in {"yesterday"}:
        y = today - timedelta(days=1)
        return Period(y, y, "yesterday")
    if p in {"this month", "current month", "month to date", "mtd", "month"}:
        s, e = month_bounds(today.year, today.month)
        return Period(s, min(e, today), f"{s.strftime('%B %Y')} (to date)")
    if p in {"last month", "previous month", "prior month"}:
        y, mo = _shift_month(today.year, today.month, -1)
        s, e = month_bounds(y, mo)
        return Period(s, e, s.strftime("%B %Y"))
    if p in {"this week", "week to date", "wtd", "week"}:
        s = today - timedelta(days=today.weekday())
        return Period(s, today, "this week")
    if p in {"last week", "previous week"}:
        s = today - timedelta(days=today.weekday() + 7)
        return Period(s, s + timedelta(days=6), "last week")
    if p in {"this year", "year to date", "ytd", "year"}:
        return Period(date(today.year, 1, 1), today, f"{today.year} (to date)")
    if p in {"last year", "previous year"}:
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1))
    if p in {"this quarter", "quarter", "qtd"}:
        q = (today.month - 1) // 3
        s = date(today.year, q * 3 + 1, 1)
        return Period(s, today, f"Q{q + 1} {today.year} (to date)")
    if p in {"last quarter", "previous quarter"}:
        q = (today.month - 1) // 3 - 1
        y = today.year
        if q < 0:
            q, y = 3, y - 1
        s = date(y, q * 3 + 1, 1)
        _, e = month_bounds(y, q * 3 + 3)
        return Period(s, e, f"Q{q + 1} {y}")
    if p in {"all", "all time", "everything", "ever"}:
        return Period(date(2000, 1, 1), today, "all time")

    m = re.match(r"^(?:last|past|previous) (\d+) (day|week|month|year)s?$", p)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "day":
            s = today - timedelta(days=n - 1)
        elif unit == "week":
            s = today - timedelta(days=7 * n - 1)
        elif unit == "month":
            y, mo = _shift_month(today.year, today.month, -n)
            s = date(y, mo, min(today.day, calendar.monthrange(y, mo)[1])) + timedelta(days=1)
        else:
            s = date(today.year - n, today.month, min(today.day, 28)) + timedelta(days=1)
        return Period(s, today, f"last {n} {unit}{'s' if n != 1 else ''}")

    m = re.match(r"^(?:in |for )?([a-z]+)(?: (\d{4}))?$", p)
    if m and m.group(1) in MONTH_NAMES:
        mo = MONTH_NAMES[m.group(1)]
        year = int(m.group(2)) if m.group(2) else (today.year if mo <= today.month else today.year - 1)
        s, e = month_bounds(year, mo)
        return Period(s, e, s.strftime("%B %Y"))

    raise ValueError(
        f"Unrecognised period {period!r}. Try 'this month', 'last month', 'last 30 days', 'YYYY-MM', "
        "'august 2026', 'ytd', or 'YYYY-MM-DD..YYYY-MM-DD'."
    )


PERIOD_PHRASES = [
    "month to date", "year to date", "this month", "last month", "previous month", "this week", "last week",
    "this year", "last year", "this quarter", "last quarter", "yesterday", "today", "all time", "ytd", "mtd",
]


def find_period_in_text(text: str, today: date | None = None) -> tuple[Period, str] | None:
    """Locate a period phrase inside a sentence. Returns (period, matched_phrase) or None."""
    t = " " + re.sub(r"\s+", " ", re.sub(r"[?!.,;:\"]+", " ", text.lower())) + " "
    for phrase in PERIOD_PHRASES:
        if f" {phrase} " in t:
            return resolve_period(phrase, today), phrase
    m = re.search(r"\b(?:last|past|previous) (\d+) (days?|weeks?|months?|years?)\b", t)
    if m:
        return resolve_period(m.group(0).strip(), today), m.group(0).strip()
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\s*(?:\.\.|to|until|through)\s*(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        return resolve_period(f"{m.group(1)}..{m.group(2)}", today), m.group(0).strip()
    m = re.search(r"\b(\d{4}-\d{2})\b", t)
    if m:
        return resolve_period(m.group(1), today), m.group(1)
    m = re.search(r"\b(?:in |for |during )?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\b(?: (\d{4}))?", t)
    if m:
        phrase = m.group(1) + (f" {m.group(2)}" if m.group(2) else "")
        return resolve_period(phrase, today), phrase
    return None
