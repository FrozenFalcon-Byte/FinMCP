"""Receipt parsing: vision LLM when available, Tesseract OCR plus heuristics otherwise."""
from __future__ import annotations

import base64
import mimetypes
import re
import shutil
from pathlib import Path
from typing import Any

from .common import clean_text, find_date, parse_amount
from .models import LineItem, ParsedTransaction, ParseResult

TOTAL_WORDS = ("grand total", "net payable", "amount payable", "total payable", "amount due", "balance due", "net amount", "total amount", "total")
NOT_ITEM = ("subtotal", "sub total", "sub-total", "total", "tax", "gst", "cgst", "sgst", "igst", "vat", "discount", "cash", "change",
            "tender", "paid", "card", "upi", "round", "qty", "amount", "price", "item", "gstin", "invoice", "bill", "date", "time",
            "thank", "visit", "phone", "tel", "www", "http", "cashier", "table", "order", "receipt", "customer", "balance", "service charge")
SKIP_MERCHANT_LINES = ("tax invoice", "invoice", "receipt", "bill", "gstin", "cash memo", "retail invoice", "original", "duplicate", "copy")


def ocr_image(path: str | Path) -> str:
    if shutil.which("tesseract") is None:
        raise RuntimeError("Tesseract is not installed (brew install tesseract) and no LLM is configured for vision OCR.")
    import pytesseract
    from PIL import Image, ImageOps

    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = ImageOps.grayscale(img)
    if img.width < 1000:
        scale = 1000 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return pytesseract.image_to_string(img, config="--psm 6")


def _amounts_in(line: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"(?<![\d.])(\d[\d,]*\.\d{2})(?![\d.])", line)]


def parse_receipt_text(text: str, source_name: str | None = None) -> ParseResult:
    lines = [clean_text(ln) or "" for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    warnings: list[str] = []
    if not lines:
        return ParseResult(source_kind="receipt", source_name=source_name, parser="ocr-heuristics", warnings=["no text found"])

    merchant = next((ln for ln in lines[:6] if re.search(r"[A-Za-z]{3,}", ln) and not any(k in ln.lower() for k in SKIP_MERCHANT_LINES)
                     and not re.search(r"\d{2}[/\-]\d{2}", ln)), lines[0])
    merchant = re.sub(r"[^A-Za-z0-9&'.\- ]+", " ", merchant).strip()[:60] or "UNKNOWN"
    iso = find_date(text)
    if not iso:
        warnings.append("no date found; using today")
    total: float | None = None
    total_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        low = lines[i].lower()
        if any(w in low for w in TOTAL_WORDS) and not any(w in low for w in ("subtotal", "sub total", "sub-total", "total qty", "total items")):
            amts = _amounts_in(lines[i]) or ([parse_amount(lines[i].split()[-1])] if parse_amount(lines[i].split()[-1]) else [])
            if amts:
                total, total_idx = amts[-1], i
                break
    if total is None:
        all_amts = [a for ln in lines for a in _amounts_in(ln)]
        if not all_amts:
            return ParseResult(source_kind="receipt", source_name=source_name, parser="ocr-heuristics", warnings=warnings + ["no amount found"])
        total = max(all_amts)
        warnings.append("no total line; used the largest amount")
    items: list[LineItem] = []
    for ln in lines[1:total_idx]:
        low = ln.lower()
        if any(w in low for w in NOT_ITEM):
            continue
        amts = _amounts_in(ln)
        if not amts:
            continue
        name = re.sub(r"(\d+(?:\.\d+)?\s*[xX*]\s*\d[\d,]*(?:\.\d{2})?|\d[\d,]*\.\d{2})", " ", ln)
        name = re.sub(r"\s+", " ", name).strip(" -:.@")
        if not re.search(r"[A-Za-z]{2,}", name):
            continue
        qty = None
        unit = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*[xX*]\s*(\d[\d,]*(?:\.\d{2})?)", ln)
        if m:
            qty, unit = float(m.group(1)), float(m.group(2).replace(",", ""))
        items.append(LineItem(name=name[:60], quantity=qty, unit_price=unit, total=amts[-1]))
    from datetime import date as _d

    tx = ParsedTransaction(
        date=iso or _d.today().isoformat(), amount=round(total, 2), direction="debit", merchant=merchant,
        description=f"Receipt: {merchant}" + (f", {len(items)} items" if items else ""), raw_text=text[:1500], source="receipt",
        confidence=0.75 if iso else 0.55, line_items=items,
    )
    return ParseResult(source_kind="receipt", source_name=source_name, parser="ocr-heuristics", transactions=[tx], warnings=warnings,
                       raw_excerpt="\n".join(lines[:12]))


def parse_receipt(path: str | Path, provider: Any = None) -> ParseResult:
    p = Path(path)
    media_type = mimetypes.guess_type(p.name)[0] or "image/png"
    if provider is not None and getattr(provider, "is_llm", False):
        try:
            ex = provider.extract_receipt(p.read_bytes(), media_type)
            if ex and ex.total:
                iso = find_date(ex.date or "") if ex.date else None
                from datetime import date as _d

                tx = ParsedTransaction(
                    date=iso or _d.today().isoformat(), amount=abs(ex.total), direction="debit", merchant=ex.merchant or "UNKNOWN",
                    description=f"Receipt: {ex.merchant}" + (f", paid by {ex.payment_method}" if ex.payment_method else ""),
                    raw_text=f"vision:{p.name}", source="receipt", confidence=ex.confidence,
                    line_items=[LineItem(name=i.name, quantity=i.quantity, unit_price=i.unit_price, total=i.total) for i in ex.line_items],
                )
                return ParseResult(source_kind="receipt", source_name=p.name, parser="vision-llm", transactions=[tx],
                                   warnings=[] if iso else ["model returned no usable date; using today"])
        except Exception as exc:
            fallback_note = f"vision extraction failed ({exc}); used OCR"
        else:
            fallback_note = "vision extraction returned nothing; used OCR"
    else:
        fallback_note = None
    text = ocr_image(p)
    result = parse_receipt_text(text, p.name)
    result.parser = "tesseract+heuristics"
    if fallback_note:
        result.warnings.insert(0, fallback_note)
    return result


def image_to_base64(path: str | Path) -> tuple[str, str]:
    p = Path(path)
    return base64.standard_b64encode(p.read_bytes()).decode("ascii"), mimetypes.guess_type(p.name)[0] or "image/png"
