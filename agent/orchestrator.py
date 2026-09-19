"""The agent loop: user text in, events out, tools executed over MCP, history kept per conversation."""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import events
from .drivers import DriverError, DriverFinal, ModelDriver
from .mcp_client import MCPConnection
from .prompts import build_system_prompt

log = logging.getLogger("finmcp.agent")


@dataclass
class Conversation:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    turns: int = 0
    title: str | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")


class Agent:
    def __init__(self, connection: MCPConnection, driver: ModelDriver, *, currency: str = "INR",
                 max_iterations: int = 12, tool_result_max_chars: int = 60000):
        self.connection = connection
        self.driver = driver
        self.currency = currency
        self.max_iterations = max_iterations
        self.tool_result_max_chars = tool_result_max_chars
        self.conversations: dict[str, Conversation] = {}
        self.system: str = ""
        self.tools: list[dict[str, Any]] = []
        self._ready = False

    # ------------------------------------------------------------ setup

    async def prepare(self) -> None:
        mcp_tools = await self.connection.list_tools(refresh=True)
        self.tools = self.connection.to_anthropic_tools(mcp_tools)
        categories: list[dict[str, Any]] | None = None
        try:
            categories = await self.connection.read_resource_json("finmcp://categories")
        except Exception as exc:  # the prompt still works without the live list
            log.warning("could not read categories resource: %s", exc)
        self.system = build_system_prompt(currency=self.currency, categories=categories, server_instructions=self.connection.instructions)
        self._ready = True

    # ------------------------------------------------------------ conversations

    def conversation(self, conversation_id: str | None = None) -> Conversation:
        cid = conversation_id or uuid.uuid4().hex[:12]
        conv = self.conversations.get(cid)
        if conv is None:
            conv = Conversation(id=cid)
            self.conversations[cid] = conv
        return conv

    def reset(self, conversation_id: str) -> bool:
        return self.conversations.pop(conversation_id, None) is not None

    def transcript(self, conversation_id: str) -> list[dict[str, Any]]:
        """History reduced to what a UI shows: user text, assistant text, tool calls and results."""
        conv = self.conversations.get(conversation_id)
        if conv is None:
            return []
        out: list[dict[str, Any]] = []
        for m in conv.messages:
            if isinstance(m["content"], str):
                out.append({"role": m["role"], "type": "text", "text": m["content"]})
                continue
            for b in m["content"]:
                t = b.get("type")
                if t == "text":
                    out.append({"role": m["role"], "type": "text", "text": b["text"]})
                elif t == "tool_use":
                    out.append({"role": "assistant", "type": "tool_call", "id": b["id"], "name": b["name"], "input": b["input"]})
                elif t == "tool_result":
                    c = b.get("content")
                    text = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                    out.append({"role": "tool", "type": "tool_result", "id": b["tool_use_id"], "ok": not b.get("is_error", False), "preview": text[:400]})
        return out

    # ------------------------------------------------------------ the loop

    async def run(self, user_text: str, conversation_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        if not self._ready:
            await self.prepare()
        conv = self.conversation(conversation_id)
        if not user_text.strip():
            yield events.error("Empty message.", fatal=True)
            return
        conv.messages.append({"role": "user", "content": user_text})
        conv.turns += 1
        if conv.title is None:
            conv.title = user_text.strip()[:60]
        texts: list[str] = []
        iterations = 0
        last_stop: str | None = None
        usage_total: dict[str, int] = {}
        replied = False

        while iterations < self.max_iterations:
            iterations += 1
            final: DriverFinal | None = None
            turn_text: list[str] = []
            try:
                async for ev in self.driver.stream(system=self.system, messages=conv.messages, tools=self.tools):
                    if ev["type"] == "text_delta":
                        turn_text.append(ev["text"])
                        yield events.text_delta(ev["text"])
                    elif ev["type"] == "final":
                        final = ev["final"]
            except DriverError as exc:
                if not replied:
                    conv.messages.pop()  # keep history consistent: the user turn never got an answer
                    conv.turns -= 1
                yield events.error(str(exc), fatal=True)
                yield events.done("".join(turn_text), conversation_id=conv.id, iterations=iterations, stop_reason="error", usage=None)
                return
            if final is None:
                yield events.error("The model returned no message.", fatal=True)
                break
            if turn_text:
                texts.append("".join(turn_text))
            conv.messages.append({"role": "assistant", "content": final.content})
            conv.touch()
            replied = True
            last_stop = final.stop_reason
            for k, v in (final.usage or {}).items():
                if isinstance(v, int):
                    usage_total[k] = usage_total.get(k, 0) + v

            if final.stop_reason == "tool_use":
                tool_uses = [b for b in final.content if b.get("type") == "tool_use"]
                results: list[dict[str, Any]] = []
                for tu in tool_uses:
                    args = tu.get("input") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    yield events.tool_call(tu["id"], tu["name"], args)
                    outcome = await self.connection.call_tool(tu["name"], args)
                    content = self._truncate(outcome.content)
                    small = outcome.data if outcome.data is not None and len(outcome.text) <= 20000 else None
                    yield events.tool_result(tu["id"], tu["name"], outcome.ok, outcome.text[:400], outcome.elapsed_ms, data=small)
                    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": tu["id"], "content": content}
                    if not outcome.ok:
                        block["is_error"] = True
                    results.append(block)
                conv.messages.append({"role": "user", "content": results})
                continue
            if final.stop_reason == "pause_turn":
                continue
            if final.stop_reason == "refusal":
                detail = (final.stop_details or {}).get("explanation") or "the request was declined by the model's safety system"
                yield events.error(f"The model declined: {detail}")
                break
            if final.stop_reason == "max_tokens":
                yield events.error("The answer hit the length limit and was cut off.")
                break
            break
        else:
            yield events.error(f"Stopped after {self.max_iterations} tool rounds without a final answer.")

        yield events.done("\n\n".join(t for t in texts if t.strip()), conversation_id=conv.id, iterations=iterations,
                          stop_reason=last_stop, usage=usage_total or None)

    def _truncate(self, content: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        budget = self.tool_result_max_chars
        for b in content:
            if b.get("type") == "text" and len(b["text"]) > budget:
                out.append({"type": "text", "text": b["text"][:budget] + f"\n...[truncated {len(b['text']) - budget} characters]"})
            else:
                out.append(b)
        return out
