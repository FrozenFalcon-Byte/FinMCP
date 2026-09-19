"""The application's MCP host: what sits between the app's screens and its MCP clients.

- `Trace` keeps the last N protocol messages per account and fans them out over the account's event feed, so the
  app can show the protocol at work.
- `ElicitationBroker` answers the server's `elicitation/create` requests by asking the person in the browser and
  waiting for the reply (or timing out).
- `sampling_callback` lets the server borrow the app's model through `sampling/createMessage`.
- `roots_callback` tells the server which folder it may read files from.
- `watch_resources` opens a `subscriptions/listen` stream and turns resource-updated events into UI refreshes.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp.types as mt
from pydantic import AnyUrl

from finmcp.db.events import events

from .drivers import ModelDriver
from .mcp_client import MCPConnection

log = logging.getLogger("finmcp.host")
ELICIT_TIMEOUT_S = 90.0


class Trace:
    def __init__(self, user_id: str, size: int = 300):
        self.user_id = user_id
        self.entries: deque[dict[str, Any]] = deque(maxlen=size)
        self.seq = 0
        self.by_kind: Counter[str] = Counter()
        self.by_method: Counter[str] = Counter()
        self.by_client: Counter[str] = Counter()
        self.started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def record(self, entry: dict[str, Any]) -> None:
        self.seq += 1
        entry = {"seq": self.seq, **entry}
        self.entries.append(entry)
        self.by_kind[str(entry.get("kind"))] += 1
        self.by_method[str(entry.get("method"))] += 1
        self.by_client[str(entry.get("client"))] += 1
        events.emit(self.user_id, type="mcp", **entry)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self.entries)[-limit:]

    def stats(self) -> dict[str, Any]:
        return {"total": self.seq, "since": self.started, "by_kind": dict(self.by_kind), "by_method": dict(self.by_method),
                "by_client": dict(self.by_client)}


class ElicitationBroker:
    """Pending questions from the server, answered by the browser through the API."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.pending: dict[str, tuple[asyncio.Future[mt.ElicitResult], dict[str, Any]]] = {}

    def callback(self, client: str) -> Callable[..., Awaitable[mt.ElicitResult]]:
        async def handler(context: Any, params: Any) -> mt.ElicitResult:
            return await self.ask(client, params)
        return handler

    async def ask(self, client: str, params: Any) -> mt.ElicitResult:
        if getattr(params, "mode", "form") != "form":
            return mt.ElicitResult(action="decline")
        qid = uuid.uuid4().hex[:10]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[mt.ElicitResult] = loop.create_future()
        question = {"id": qid, "client": client, "message": params.message, "schema": params.requested_schema,
                    "asked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.pending[qid] = (fut, question)
        events.emit(self.user_id, type="elicit", **question)
        try:
            return await asyncio.wait_for(fut, ELICIT_TIMEOUT_S)
        except TimeoutError:
            return mt.ElicitResult(action="cancel")
        finally:
            self.pending.pop(qid, None)
            events.emit(self.user_id, type="elicit_done", id=qid)

    def answer(self, qid: str, action: str, content: dict[str, Any] | None) -> bool:
        item = self.pending.get(qid)
        if item is None or item[0].done():
            return False
        item[0].set_result(mt.ElicitResult(action=action, content=content if action == "accept" else None))  # type: ignore[arg-type]
        return True

    def open(self) -> list[dict[str, Any]]:
        return [q for _, q in self.pending.values()]


def sampling_callback(driver: ModelDriver) -> Callable[..., Awaitable[Any]] | None:
    """The client-side half of sampling. Only offered when the app has a real model; otherwise the server sees no
    sampling capability and falls back to its own rules."""
    if getattr(driver, "name", "") not in {"anthropic", "openrouter"}:
        return None

    async def handler(context: Any, params: mt.CreateMessageRequestParams) -> Any:
        messages = []
        for m in params.messages:
            content = m.content if isinstance(m.content, list) else [m.content]
            text = "\n".join(str(getattr(c, "text", "") or "") for c in content)
            messages.append({"role": m.role, "content": text})
        final = None
        try:
            async for ev in driver.stream(system=params.system_prompt or "", messages=messages, tools=[]):
                if ev["type"] == "final":
                    final = ev["final"]
        except Exception as exc:  # noqa: BLE001 - reported to the server as a protocol error
            return mt.ErrorData(code=mt.INTERNAL_ERROR, message=f"sampling failed: {exc}")
        text = "".join(b.get("text", "") for b in (final.content if final else []) if b.get("type") == "text")
        return mt.CreateMessageResult(role="assistant", content=mt.TextContent(type="text", text=text),
                                      model=str(getattr(driver, "model", "claude")), stop_reason="endTurn")
    return handler


def roots_callback(paths: list[Path]) -> Callable[..., Awaitable[mt.ListRootsResult]]:
    async def handler(context: Any) -> mt.ListRootsResult:
        return mt.ListRootsResult(roots=[mt.Root(uri=AnyUrl(p.resolve().as_uri()), name=p.name) for p in paths])  # type: ignore[arg-type]
    return handler


async def watch_resources(connection: MCPConnection, user_id: str, uris: list[str]) -> None:
    """Keep a `subscriptions/listen` stream open; every resource-updated event becomes a `change` on the account feed."""
    while True:
        try:
            async for uri in connection.listen(uris):
                events.emit(user_id, type="change", uri=uri, via="subscriptions/listen")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - re-listen after a dropped stream
            log.warning("resource subscription for %s dropped (%s); re-listening", user_id, exc)
            await asyncio.sleep(1.0)


__all__ = ["ELICIT_TIMEOUT_S", "ElicitationBroker", "Trace", "roots_callback", "sampling_callback", "watch_resources"]
