"""Parse a file or pasted text, dedupe against the ledger, insert, auto-categorize."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..db.repository import Repository
from ..services.categorize import Categorizer
from .models import ParseResult
from .receipts import parse_receipt
from .sms import parse_sms_dump
from .statements import parse_csv, parse_csv_text, parse_pdf

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
KINDS = ("auto", "receipt", "statement", "csv", "sms")


def detect_kind(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return "statement"
    if ext in {".csv", ".tsv"}:
        return "csv"
    if ext in IMAGE_EXT:
        return "receipt"
    if ext in {".txt", ".log", ".sms", ".md"}:
        return "sms"
    raise ValueError(f"Cannot tell what {Path(path).name} is; pass kind='receipt' | 'statement' | 'csv' | 'sms'.")


class Importer:
    def __init__(self, repo: Repository, categorizer: Categorizer, provider: Any = None):
        self.repo = repo
        self.categorizer = categorizer
        self.provider = provider

    # ------------------------------------------------------------- parsing

    def parse_file(self, path: str | Path, kind: str = "auto") -> ParseResult:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists():
            raise ValueError(f"File not found: {p}")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        kind = detect_kind(p) if kind == "auto" else kind
        if kind == "csv":
            return parse_csv(p)
        if kind == "statement":
            if p.suffix.lower() in {".csv", ".tsv"}:
                return parse_csv(p)
            return parse_pdf(p, self.provider)
        if kind == "receipt":
            return parse_receipt(p, self.provider)
        return parse_sms_dump(p.read_text(encoding="utf-8", errors="replace"), p.name, self.provider)

    def parse_text(self, text: str, kind: str = "sms", source_name: str | None = None) -> ParseResult:
        if kind == "csv":
            return parse_csv_text(text, source_name)
        if kind == "sms":
            return parse_sms_dump(text, source_name, self.provider)
        raise ValueError("kind must be 'sms' or 'csv' for pasted text")

    # ------------------------------------------------------------- importing

    def preview(self, result: ParseResult, limit: int = 100) -> dict[str, Any]:
        rows = []
        dups = 0
        for tx in result.transactions:
            dup = self.repo.fingerprint_exists(tx.fingerprint)
            dups += int(dup)
            rows.append({**tx.model_dump(), "fingerprint": tx.fingerprint, "duplicate": dup})
        return {
            "source_kind": result.source_kind, "source_name": result.source_name, "parser": result.parser,
            "parsed": len(rows), "duplicates": dups, "new": len(rows) - dups,
            "warnings": result.warnings, "skipped": result.skipped[:50], "transactions": rows[:limit],
        }

    def commit(self, result: ParseResult, *, auto_categorize: bool = True, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {"dry_run": True, **self.preview(result)}
        inserted: list[dict[str, Any]] = []
        duplicates = 0
        for tx in result.transactions:
            row = self.repo.insert_transaction(
                date=tx.date, amount=tx.amount, merchant=tx.merchant, direction=tx.direction, description=tx.description,
                source=tx.source, raw_text=tx.raw_text, fingerprint=tx.fingerprint, ignore_duplicate=True,
                needs_review=tx.confidence < 0.7,
            )
            if row is None:
                duplicates += 1
                continue
            cat = self.categorizer.categorize(row.id) if auto_categorize else None
            if cat is None or cat["category"] is None or tx.confidence < 0.7:
                self.repo.update_transaction(row.id, needs_review=True)
            fresh = self.repo.get_transaction(row.id)
            assert fresh is not None
            inserted.append({**fresh.model_dump(), "line_items": [li.model_dump() for li in tx.line_items]})
        import_id = self.repo.record_import(result.source_kind, result.source_name, len(result.transactions), len(inserted), duplicates,
                                            {"parser": result.parser, "warnings": result.warnings, "skipped": len(result.skipped)})
        self.repo.audit("mcp:import", "import", "import", import_id,
                        {"source": result.source_name, "parsed": len(result.transactions), "inserted": len(inserted), "duplicates": duplicates})
        return {
            "dry_run": False, "import_id": import_id, "source_kind": result.source_kind, "source_name": result.source_name,
            "parser": result.parser, "parsed": len(result.transactions), "inserted": len(inserted), "duplicates": duplicates,
            "needs_review": sum(1 for t in inserted if t["needs_review"]),
            "categorized": sum(1 for t in inserted if t["category"]),
            "warnings": result.warnings, "skipped": result.skipped[:50], "transactions": inserted,
        }

    def import_file(self, path: str | Path, kind: str = "auto", *, auto_categorize: bool = True, dry_run: bool = False) -> dict[str, Any]:
        return self.commit(self.parse_file(path, kind), auto_categorize=auto_categorize, dry_run=dry_run)

    def import_text(self, text: str, kind: str = "sms", source_name: str | None = None, *, auto_categorize: bool = True, dry_run: bool = False) -> dict[str, Any]:
        return self.commit(self.parse_text(text, kind, source_name), auto_categorize=auto_categorize, dry_run=dry_run)
