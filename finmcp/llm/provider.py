"""LLM providers. `AnthropicProvider` talks to Claude through the official SDK; `RuleBasedProvider`
is the deterministic offline fallback so every tool keeps working without an API key."""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date
from typing import Any, Literal, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config import Settings
from ..db.repository import Category
from ..taxonomy import match_keywords
from .prompts import CATEGORIZE_SYSTEM, EXTRACT_RECEIPT_SYSTEM, EXTRACT_TRANSACTIONS_SYSTEM, TEXT_TO_SQL_SYSTEM
from .rule_sql import UnsupportedQuestion, rule_based_sql

log = logging.getLogger("finmcp.llm")


class CategoryGuess(BaseModel):
    category: str = Field(description="Exactly one category name from the provided list")
    confidence: float = Field(ge=0, le=1, description="Calibrated confidence between 0 and 1")
    reasoning: str = Field(default="", description="One short sentence on the decisive signal")


class SQLGuess(BaseModel):
    sql: str = Field(description="A single PostgreSQL SELECT statement")
    explanation: str = Field(default="", description="How the question was interpreted: period, filters, aggregation")


class ExtractedLineItem(BaseModel):
    name: str
    quantity: float | None = None
    unit_price: float | None = None
    total: float | None = None


class ReceiptExtraction(BaseModel):
    merchant: str = Field(description="Store or restaurant name as printed")
    date: str | None = Field(default=None, description="Date on the receipt, ISO YYYY-MM-DD if legible")
    total: float = Field(description="Final amount paid")
    currency: str = Field(default="INR")
    payment_method: str | None = Field(default=None, description="cash, card, upi, ... if shown")
    line_items: list[ExtractedLineItem] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, description="How legible and unambiguous the receipt is")


class ExtractedTransaction(BaseModel):
    date: str = Field(description="ISO YYYY-MM-DD")
    amount: float = Field(description="Positive amount")
    direction: Literal["debit", "credit"]
    merchant: str
    description: str | None = None
    confidence: float = Field(ge=0, le=1)


class ExtractedTransactions(BaseModel):
    transactions: list[ExtractedTransaction] = Field(default_factory=list)


class LLMError(RuntimeError):
    """The model could not be reached or refused; callers degrade gracefully."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    is_llm: bool

    def categorize(self, *, merchant: str, description: str | None, amount: float, direction: str,
                   categories: list[Category], examples: list[dict[str, Any]] | None = None) -> CategoryGuess | None: ...

    def text_to_sql(self, question: str, schema_doc: str, *, today: date | None = None, previous_error: str | None = None) -> SQLGuess: ...

    def extract_receipt(self, image_bytes: bytes, media_type: str) -> ReceiptExtraction | None: ...

    def extract_transactions(self, text: str, hint: str = "") -> list[ExtractedTransaction] | None: ...

    def extract_transactions_from_pdf(self, pdf_bytes: bytes) -> list[ExtractedTransaction] | None: ...


class RuleBasedProvider:
    name = "rules"
    is_llm = False

    def categorize(self, *, merchant: str, description: str | None, amount: float, direction: str,
                   categories: list[Category], examples: list[dict[str, Any]] | None = None) -> CategoryGuess | None:
        hit = match_keywords(f"{merchant} {description or ''}")
        if not hit:
            return None
        name, kw = hit
        in_merchant = kw in merchant.lower()
        return CategoryGuess(category=name, confidence=0.8 if in_merchant else 0.7, reasoning=f"keyword '{kw}'")

    def text_to_sql(self, question: str, schema_doc: str, *, today: date | None = None, previous_error: str | None = None) -> SQLGuess:
        sql, explanation = rule_based_sql(question, today)
        return SQLGuess(sql=sql, explanation=explanation)

    def extract_receipt(self, image_bytes: bytes, media_type: str) -> ReceiptExtraction | None:
        return None

    def extract_transactions(self, text: str, hint: str = "") -> list[ExtractedTransaction] | None:
        return None

    def extract_transactions_from_pdf(self, pdf_bytes: bytes) -> list[ExtractedTransaction] | None:
        return None


class AnthropicProvider:
    name = "anthropic"
    is_llm = True

    def __init__(self, model: str = "claude-opus-5", *, fallbacks: bool = True, max_retries: int = 2, timeout: float = 60.0):
        self.model = model
        self.fallbacks = fallbacks
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(max_retries=self.max_retries, timeout=self.timeout)
        return self._client

    def _parse(self, *, system: str, user: str | list[dict[str, Any]], output_format: type[BaseModel], effort: str, max_tokens: int = 4096) -> BaseModel:
        import anthropic

        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
            output_config={"effort": effort},
        )
        try:
            if self.fallbacks:
                response = self.client.beta.messages.parse(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                response = self.client.messages.parse(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic API key is missing or invalid (set ANTHROPIC_API_KEY in .env).") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic rate limit hit; try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API (network error).") from exc
        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request.")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMError("The model returned no structured output.")
        return parsed

    def categorize(self, *, merchant: str, description: str | None, amount: float, direction: str,
                   categories: list[Category], examples: list[dict[str, Any]] | None = None) -> CategoryGuess | None:
        cat_lines = "\n".join(f"- {c.name} ({c.kind}): {c.description or ''}" for c in categories)
        example_lines = ""
        if examples:
            example_lines = "\nPreviously confirmed by the user:\n" + "\n".join(
                f"- {e['merchant']} -> {e['category']}" for e in examples[:20]
            )
        user = (
            f"Transaction\n  merchant: {merchant}\n  narration: {description or '(none)'}\n  amount: {amount:.2f}\n"
            f"  direction: {direction}\n\nCategories:\n{cat_lines}{example_lines}"
        )
        guess = self._parse(system=CATEGORIZE_SYSTEM, user=user, output_format=CategoryGuess, effort="low", max_tokens=1024)
        assert isinstance(guess, CategoryGuess)
        return guess

    def text_to_sql(self, question: str, schema_doc: str, *, today: date | None = None, previous_error: str | None = None) -> SQLGuess:
        user = f"Question: {question}"
        if previous_error:
            user += f"\n\nYour previous SQL failed with this error, fix it:\n{previous_error}"
        guess = self._parse(system=TEXT_TO_SQL_SYSTEM.format(schema=schema_doc), user=user, output_format=SQLGuess, effort="medium")
        assert isinstance(guess, SQLGuess)
        return guess

    def extract_receipt(self, image_bytes: bytes, media_type: str) -> ReceiptExtraction | None:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(image_bytes).decode("ascii")}},
            {"type": "text", "text": "Extract the purchase from this receipt."},
        ]
        out = self._parse(system=EXTRACT_RECEIPT_SYSTEM, user=content, output_format=ReceiptExtraction, effort="low", max_tokens=4096)
        assert isinstance(out, ReceiptExtraction)
        return out

    def extract_transactions(self, text: str, hint: str = "") -> list[ExtractedTransaction] | None:
        user = f"Source: {hint or 'unstructured text'}\n\n{text}"
        out = self._parse(system=EXTRACT_TRANSACTIONS_SYSTEM, user=user, output_format=ExtractedTransactions, effort="low", max_tokens=16000)
        assert isinstance(out, ExtractedTransactions)
        return out.transactions

    def extract_transactions_from_pdf(self, pdf_bytes: bytes) -> list[ExtractedTransaction] | None:
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(pdf_bytes).decode("ascii")}},
            {"type": "text", "text": "Extract every transaction row from this bank statement."},
        ]
        out = self._parse(system=EXTRACT_TRANSACTIONS_SYSTEM, user=content, output_format=ExtractedTransactions, effort="medium", max_tokens=32000)
        assert isinstance(out, ExtractedTransactions)
        return out.transactions


class OpenRouterProvider(AnthropicProvider):
    """The same prompts and output models as AnthropicProvider, answered by any OpenRouter model as plain JSON."""

    name = "openrouter"

    def _parse(self, *, system: str, user: str | list[dict[str, Any]], output_format: type[BaseModel], effort: str, max_tokens: int = 4096) -> BaseModel:
        from . import openrouter

        try:
            return openrouter.complete_json(model=self.model, system=system, user=user, output=output_format, max_tokens=max_tokens, timeout=self.timeout)
        except PermissionError as exc:
            raise LLMError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMError("Could not reach OpenRouter (network error).") from exc
        except (RuntimeError, ValueError) as exc:
            raise LLMError(str(exc)) from exc


def get_provider(settings: Settings) -> LLMProvider:
    if settings.use_llm and settings.llm_backend == "openrouter":
        return OpenRouterProvider(settings.model, fallbacks=False)
    if settings.use_llm:
        if not settings.api_key_present and settings.llm_mode == "anthropic":
            log.warning("FINMCP_LLM=anthropic but no ANTHROPIC_API_KEY is set; calls will fail until it is.")
        return AnthropicProvider(settings.model, fallbacks=settings.fallbacks)
    return RuleBasedProvider()


__all__ = ["AnthropicProvider", "OpenRouterProvider", "CategoryGuess", "ExtractedTransaction", "LLMError", "LLMProvider", "ReceiptExtraction", "RuleBasedProvider", "SQLGuess", "UnsupportedQuestion", "get_provider"]


SAMPLING_SYSTEM = ("You categorise personal-finance transactions. Pick exactly one category name from the list for each "
                   "transaction. Reply with JSON only.")


def sampling_prompt(items: list[dict[str, Any]], categories: list[Category], examples: list[dict[str, Any]] | None = None) -> str:
    """One prompt for a batch of transactions, so a single `sampling/createMessage` round trip covers them all."""
    cat_lines = "\n".join(f"- {c.name} ({c.kind}): {c.description or ''}" for c in categories)
    example_lines = ""
    if examples:
        example_lines = "\nPreviously confirmed by the user:\n" + "\n".join(f"- {e['merchant']} -> {e['category']}" for e in examples[:20])
    tx_lines = "\n".join(f"{n}. merchant: {it['merchant']} | narration: {it.get('description') or '(none)'} | amount: {float(it['amount']):.2f} | "
                         f"{it['direction']}" for n, it in enumerate(items, 1))
    return (f"Transactions:\n{tx_lines}\n\nCategories:\n{cat_lines}{example_lines}\n\n"
            'Reply with JSON only, one entry per transaction number: '
            '{"1": {"category": "<exact name from the list>", "confidence": <0..1>, "reasoning": "<one short sentence>"}}')


def parse_sampled(text: str, items: list[dict[str, Any]]) -> dict[str, CategoryGuess]:
    """Map the model's JSON answer back to merchants. Anything malformed is dropped, never guessed."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return {}
    out: dict[str, CategoryGuess] = {}
    for n, it in enumerate(items, 1):
        raw = data.get(str(n)) if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            continue
        try:
            out[str(it["merchant"]).strip().lower()] = CategoryGuess.model_validate(raw)
        except ValidationError:
            continue
    return out


class SampledProvider(RuleBasedProvider):
    """Answers with guesses the *client's* model already made through MCP sampling (`sampling/createMessage`), so the
    server needs no API key of its own. Keyed by merchant, which is what the categorizer asks about."""

    name = "sampling"
    is_llm = True

    def __init__(self, guesses: dict[str, CategoryGuess]):
        self.guesses = guesses

    def categorize(self, *, merchant: str, description: str | None, amount: float, direction: str,
                   categories: list[Category], examples: list[dict[str, Any]] | None = None) -> CategoryGuess | None:
        return self.guesses.get(merchant.strip().lower())
