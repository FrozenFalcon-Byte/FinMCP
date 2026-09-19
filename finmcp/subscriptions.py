"""Per-account resource subscriptions (MCP `subscriptions/listen`).

One process serves many accounts through several MCPServer instances (the web app's in-process server, the
assistant's, the multi-account HTTP endpoint), and resource URIs look the same for every account
(`finmcp://overview`). So the fan-out bus is per account: `RoutedBus` forwards publish/subscribe to the bus of
whichever account the current MCP request belongs to.

`pump_changes` turns repository writes (the in-process LedgerEvents feed) into `notifications/resources/updated`
events, so every client that listens, the web app, the assistant, Claude Desktop, learns about a change no matter
which client made it. A pump runs only while an account has at least one open listen stream: the first listener
starts it on the serving event loop, the last one to leave cancels it.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from mcp.server.subscriptions import InMemorySubscriptionBus, ResourceUpdated, ServerEvent

from .db.events import events

ALL_RESOURCES = (
    "finmcp://overview", "finmcp://categories", "finmcp://transactions/recent", "finmcp://summary/monthly", "finmcp://recurring",
    "finmcp://goals", "finmcp://review-queue", "finmcp://alerts", "finmcp://activity", "finmcp://imports/recent", "finmcp://status",
)
# Which resources a write invalidates. Every write touches the overview and the activity trail.
AFFECTED: dict[str, tuple[str, ...]] = {
    "transaction": ("finmcp://overview", "finmcp://activity", "finmcp://transactions/recent", "finmcp://summary/monthly", "finmcp://recurring",
                    "finmcp://review-queue", "finmcp://alerts", "finmcp://status"),
    "category": ("finmcp://overview", "finmcp://activity", "finmcp://categories", "finmcp://alerts", "finmcp://status"),
    "goal": ("finmcp://overview", "finmcp://activity", "finmcp://goals", "finmcp://status"),
    "emi": ("finmcp://overview", "finmcp://activity", "finmcp://status"),
    "import": ("finmcp://overview", "finmcp://activity", "finmcp://imports/recent"),
    "ledger": ALL_RESOURCES,
}


class AccountBus(InMemorySubscriptionBus):
    def __init__(self, user_id: str) -> None:
        super().__init__()
        self.user_id = user_id
        self.listeners = 0
        self.pump: asyncio.Task[None] | None = None

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        unsubscribe = super().subscribe(listener)
        self.listeners += 1
        if self.pump is None or self.pump.done():
            self.pump = asyncio.get_running_loop().create_task(pump_changes(self), name="finmcp-resource-pump")
        done = False

        def release() -> None:
            nonlocal done
            if done:
                return
            done = True
            unsubscribe()
            self.listeners -= 1
            if self.listeners == 0 and self.pump is not None:
                self.pump.cancel()
                self.pump = None
        return release


class AccountBuses:
    def __init__(self) -> None:
        self._buses: dict[str, AccountBus] = {}
        self._lock = threading.Lock()

    def bus_for(self, user_id: str) -> AccountBus:
        with self._lock:
            bus = self._buses.get(user_id)
            if bus is None:
                bus = self._buses[user_id] = AccountBus(user_id)
            return bus

    def forget(self, user_id: str) -> None:
        with self._lock:
            bus = self._buses.pop(user_id, None)
        if bus is not None and bus.pump is not None:
            bus.pump.cancel()


buses = AccountBuses()


class RoutedBus:
    """A `SubscriptionBus` that resolves the account per call: a fixed account for bound servers, the request's
    principal (carried in a contextvar by the SDK) for the multi-account HTTP endpoint."""

    def __init__(self, resolve_user: Callable[[], str | None]):
        self._resolve = resolve_user

    async def publish(self, event: ServerEvent) -> None:
        user_id = self._resolve()
        if user_id:
            await buses.bus_for(user_id).publish(event)

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        user_id = self._resolve()
        if not user_id:
            raise RuntimeError("subscriptions/listen needs an authenticated account")
        return buses.bus_for(user_id).subscribe(listener)


async def pump_changes(bus: AccountBus) -> None:
    """Forward the account's repository writes to its subscription bus as resource-updated events. Runs until cancelled."""
    async with events.subscribe(bus.user_id) as queue:
        while True:
            ev = await queue.get()
            if ev.get("type") != "write":
                continue
            for uri in AFFECTED.get(str(ev.get("entity") or ""), ALL_RESOURCES):
                await bus.publish(ResourceUpdated(uri=uri))


__all__ = ["AFFECTED", "ALL_RESOURCES", "AccountBus", "AccountBuses", "RoutedBus", "buses", "pump_changes"]
