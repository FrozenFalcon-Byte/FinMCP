"""Model drivers. The orchestrator streams events from a driver; drivers never touch MCP.

- AnthropicDriver: Claude through the official SDK (streaming, adaptive thinking, refusal fallbacks).
- LocalDriver: no API key needed. Routes the question to one FinMCP tool and renders the result.
- ScriptedDriver: deterministic turns for tests.
"""
from __future__ import annotations

import itertools
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


class DriverError(RuntimeError):
    """The model could not be reached; the orchestrator reports it and stops the turn."""


@dataclass
class DriverFinal:
    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: dict[str, Any] | None = None
    model: str | None = None
    stop_details: dict[str, Any] | None = None


class ModelDriver(Protocol):
    name: str

    def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Yield {"type": "text_delta", "text": ...} events and finally {"type": "final", "final": DriverFinal}."""
        ...


# ---------------------------------------------------------------------- Anthropic


class AnthropicDriver:
    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5", *, effort: str = "medium", max_tokens: int = 64000,
                 fallbacks: bool = True, max_retries: int = 2, timeout: float = 600.0):
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallbacks = fallbacks
        self.max_retries = max_retries
        self.timeout = timeout
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(max_retries=self.max_retries, timeout=self.timeout)
        return self._client

    async def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        import anthropic

        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
            output_config={"effort": self.effort},
        )
        if self.fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        try:
            async with self.client.beta.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                        yield {"type": "text_delta", "text": event.delta.text}
                final = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise DriverError("Anthropic API key is missing or invalid. Set ANTHROPIC_API_KEY in .env.") from exc
        except anthropic.RateLimitError as exc:
            raise DriverError("Anthropic rate limit reached; try again in a moment.") from exc
        except anthropic.BadRequestError as exc:
            raise DriverError(f"Anthropic rejected the request: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise DriverError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise DriverError("Could not reach the Anthropic API (network error).") from exc
        content = [b.model_dump(mode="json", exclude_none=True) for b in final.content]
        usage = final.usage.model_dump(mode="json", exclude_none=True) if getattr(final, "usage", None) else None
        details = getattr(final, "stop_details", None)
        yield {"type": "final", "final": DriverFinal(
            content=content, stop_reason=final.stop_reason, usage=usage, model=getattr(final, "model", None),
            stop_details=details.model_dump(mode="json", exclude_none=True) if details else None,
        )}


# ---------------------------------------------------------------------- Local (no LLM)


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m["role"] != "user":
            continue
        c = m["content"]
        if isinstance(c, str):
            return c
        texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def _pending_tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last = messages[-1] if messages else None
    if not last or last["role"] != "user" or not isinstance(last["content"], list):
        return []
    return [b for b in last["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


def _money(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{abs(f):,.2f}"
    return ("-" if f < 0 else "") + s


def _table(columns: list[str], rows: list[list[Any]], limit: int = 15) -> str:
    head = "| " + " | ".join(str(c) for c in columns) + " |"
    sep = "|" + "|".join(" --- " for _ in columns) + "|"
    body = []
    for r in rows[:limit]:
        cells = [(_money(v) if isinstance(v, float) else str(v)) if isinstance(v, (int, float)) and not isinstance(v, bool)
                 else ("" if v is None else str(v)) for v in r]
        body.append("| " + " | ".join(cells) + " |")
    more = f"\n... {len(rows) - limit} more rows" if len(rows) > limit else ""
    return "\n".join([head, sep, *body]) + more


class LocalDriver:
    """Deterministic stand-in when no model is configured. One tool call per question, then a rendered answer."""

    name = "local"
    NOTICE = "(No ANTHROPIC_API_KEY set, so this answer comes from FinMCP's built-in query engine, not a language model.)\n\n"

    def __init__(self) -> None:
        self._ids = itertools.count(1)

    def _route(self, question: str, tools: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        q = question.lower()
        names = {t["name"] for t in tools}
        if "budget" in q and "get_budget_summary" in names:
            m = re.search(r"\b(\d{4}-\d{2})\b|\blast month\b", q)
            return "get_budget_summary", ({"month": m.group(0)} if m else {})
        if re.search(r"\b(uncategori[sz]ed|needs? review|review queue)\b", q) and "list_transactions" in names:
            return "list_transactions", {"needs_review_only": True, "limit": 25}
        if re.search(r"\b(overview|summary|summari[sz]e|how am i doing|where did my money go)\b", q) and "get_summary" in names:
            m = re.search(r"\b(last month|this month|last \d+ days|ytd|\d{4}-\d{2})\b", q)
            return "get_summary", {"period": m.group(0) if m else "this month", "group_by": "category"}
        return "query_transactions", {"question": question}

    def _render(self, name: str, block: dict[str, Any]) -> str:
        raw = block.get("content")
        text = raw if isinstance(raw, str) else "\n".join(b.get("text", "") for b in raw or [] if isinstance(b, dict))
        if block.get("is_error"):
            return self.NOTICE + f"I couldn't answer that: {text.replace('Error executing tool ', '').split(': ', 1)[-1]}"
        try:
            data = json.loads(text)
        except ValueError:
            return self.NOTICE + text
        if name == "query_transactions":
            cols, rows = data.get("columns", []), data.get("rows", [])
            parts = [f"Interpretation: {data.get('explanation', '')}".rstrip(": ")]
            parts.append(_table(cols, rows) if rows else "No matching transactions.")
            parts.append(f"```sql\n{data.get('sql', '')}\n```")
            return self.NOTICE + "\n\n".join(parts)
        if name == "get_budget_summary":
            rows = [[c["category"], c["spent"], c.get("budget_limit", ""), c.get("used_pct", ""), c["status"]] for c in data.get("categories", []) if c.get("status") != "no_budget"]
            return self.NOTICE + f"Budgets for {data.get('label')}\n\n" + _table(["category", "spent", "limit", "used %", "status"], rows, 30)
        if name == "get_summary":
            t = data.get("totals", {})
            rows = [[b.get("category", b.get("merchant", "")), b["spent"], b.get("count", ""), b.get("share_pct", "")] for b in data.get("breakdown", [])]
            head = f"{data['period']['label']}: spent {_money(t.get('spent'))}, received {_money(t.get('received'))}, net {_money(t.get('net'))} over {t.get('transaction_count')} transactions."
            return self.NOTICE + head + "\n\n" + _table(["category", "spent", "count", "share %"], rows)
        if name == "list_transactions":
            rows = [[x["date"], x["merchant"], x["amount"], x.get("category") or "-", x.get("description") or ""] for x in data.get("transactions", [])]
            return self.NOTICE + f"{data.get('total', 0)} matching transactions.\n\n" + _table(["date", "merchant", "amount", "category", "description"], rows, 25)
        return self.NOTICE + "```json\n" + json.dumps(data, indent=2)[:4000] + "\n```"

    async def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        pending = _pending_tool_results(messages)
        if pending:
            # find the tool name from the previous assistant turn
            name = "query_transactions"
            for m in reversed(messages[:-1]):
                if m["role"] == "assistant":
                    for b in m["content"]:
                        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") == pending[0].get("tool_use_id"):
                            name = b["name"]
                    break
            text = self._render(name, pending[0])
            yield {"type": "text_delta", "text": text}
            yield {"type": "final", "final": DriverFinal(content=[{"type": "text", "text": text}], stop_reason="end_turn")}
            return
        question = _last_user_text(messages).strip()
        name, args = self._route(question, tools)
        block = {"type": "tool_use", "id": f"local_{next(self._ids)}", "name": name, "input": args}
        yield {"type": "final", "final": DriverFinal(content=[block], stop_reason="tool_use")}


# ---------------------------------------------------------------------- Scripted (tests)


@dataclass
class ScriptedDriver:
    """Feed it a list of turns; each turn is a list of content blocks (text / tool_use)."""

    turns: list[list[dict[str, Any]]]
    name: str = "scripted"
    calls: list[dict[str, Any]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    async def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        if not self.turns:
            raise DriverError("scripted driver ran out of turns")
        blocks = [dict(b) for b in self.turns.pop(0)]
        for b in blocks:
            if b["type"] == "tool_use" and "id" not in b:
                b["id"] = f"toolu_scripted_{next(self._ids)}"
            if b["type"] == "text":
                half = max(1, len(b["text"]) // 2)
                yield {"type": "text_delta", "text": b["text"][:half]}
                yield {"type": "text_delta", "text": b["text"][half:]}
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        yield {"type": "final", "final": DriverFinal(content=blocks, stop_reason=stop, usage={"input_tokens": 1, "output_tokens": 1})}


def make_driver(kind: str = "auto", *, model: str = "claude-opus-5", effort: str = "medium", fallbacks: bool = True,
                api_key_present: bool = False) -> ModelDriver:
    if kind == "auto":
        kind = "anthropic" if api_key_present else "local"
    if kind == "anthropic":
        return AnthropicDriver(model, effort=effort, fallbacks=fallbacks)
    if kind == "local":
        return LocalDriver()
    raise ValueError(f"unknown driver {kind!r}")
