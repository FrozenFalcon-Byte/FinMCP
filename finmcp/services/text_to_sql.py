"""Natural-language questions -> guarded SQL -> rows."""
from __future__ import annotations

from datetime import date
from typing import Any

from ..db.repository import Repository
from ..llm.prompts import schema_doc
from ..llm.provider import LLMError, LLMProvider, UnsupportedQuestion


class QueryService:
    def __init__(self, repo: Repository, provider: LLMProvider, currency: str = "INR"):
        self.repo = repo
        self.provider = provider
        self.currency = currency

    def answer(self, question: str, limit: int = 200, today: date | None = None) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("Ask a question, e.g. 'how much did I spend on food last month'.")
        doc = schema_doc(self.currency, today)
        try:
            guess = self.provider.text_to_sql(question, doc, today=today)
        except UnsupportedQuestion as exc:
            raise ValueError(str(exc)) from exc
        except LLMError as exc:
            raise ValueError(f"The language model is unavailable ({exc}). Use list_transactions, get_summary or run_sql instead.") from exc
        sql = guess.sql.strip()
        try:
            cols, rows, truncated = self.repo.select(sql, limit=limit)
        except ValueError as first_error:
            if not self.provider.is_llm:
                raise
            guess = self.provider.text_to_sql(question, doc, today=today, previous_error=str(first_error))
            sql = guess.sql.strip()
            cols, rows, truncated = self.repo.select(sql, limit=limit)
        return {
            "question": question, "sql": sql, "explanation": guess.explanation, "provider": self.provider.name,
            "columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated,
            "records": [dict(zip(cols, r, strict=False)) for r in rows[:50]],
        }
