"""In-process change feed. Every ledger write publishes here; the API streams it to the web app over SSE.

Thread-safe: repository writes happen in worker threads while subscribers wait on asyncio queues."""
from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any


class LedgerEvents:
    def __init__(self) -> None:
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]]] = {}
        self._lock = threading.Lock()
        self.count = 0
        self._versions: dict[str, int] = {}

    def emit(self, user_id: str, **event: Any) -> None:
        payload = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **event}
        with self._lock:
            self.count += 1
            if event.get("type") == "write":
                self._versions[user_id] = self._versions.get(user_id, 0) + 1
            targets = list(self._subs.get(user_id, ()))
        for loop, queue in targets:
            with contextlib.suppress(RuntimeError):  # loop closed
                loop.call_soon_threadsafe(queue.put_nowait, payload)

    @asynccontextmanager
    async def subscribe(self, user_id: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        key = (loop, queue)
        with self._lock:
            self._subs.setdefault(user_id, set()).add(key)
        try:
            yield queue
        finally:
            with self._lock:
                subs = self._subs.get(user_id)
                if subs:
                    subs.discard(key)
                    if not subs:
                        self._subs.pop(user_id, None)

    def version(self, user_id: str) -> int:
        """Bumps on every write to the account from this process; read caches compare it to know they are stale."""
        with self._lock:
            return self._versions.get(user_id, 0)

    def subscribers(self, user_id: str | None = None) -> int:
        with self._lock:
            if user_id is not None:
                return len(self._subs.get(user_id, ()))
            return sum(len(s) for s in self._subs.values())


events = LedgerEvents()
