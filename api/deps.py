"""Application context for the API.

A `Registry` lives for the process: the database, the account store, the authenticator, the model driver, the
multi-account MCP server behind /mcp, and one `AppContext` per signed-in account. An `AppContext` holds two
in-process MCP connections to that account's ledger (one labelled 'web' for the app's own calls, one labelled
'assistant' for the in-app agent) so the audit trail says who did what. The API never touches ledger tables directly.

Both connections are full MCP clients: they offer the server elicitation (answered by the person in the browser via
`ElicitationBroker`), roots (the account's upload folder) and, when a real model is configured, sampling. Every
message is recorded in the account's `Trace`, and the 'web' connection keeps a `subscriptions/listen` stream open so
resource-updated notifications, whichever client caused them, refresh the screens.

MCP connections are anyio task groups and must be entered and exited by the same task, so the registry runs one
background "host" task that opens every connection in a child task of its own and keeps it there until shutdown.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
from fastapi import HTTPException, Request

from agent import Agent, MCPConnection
from agent.drivers import ModelDriver
from agent.host import ElicitationBroker, Trace, roots_callback, sampling_callback, watch_resources
from finmcp.config import ROOT, Settings
from finmcp.db import Database, database_for
from finmcp.db.accounts import AccountStore, Principal, Profile
from finmcp.server import create_server
from finmcp.subscriptions import ALL_RESOURCES, buses

from .auth import Authenticator, RateLimiter, bearer_from_header

log = logging.getLogger("finmcp.api")
UPLOAD_ROOT = ROOT / "data" / "uploads"


@dataclass
class AppContext:
    """Everything a request needs for one account."""

    principal: Principal
    profile: Profile
    settings: Settings
    connection: MCPConnection      # client label "web"
    assistant: MCPConnection       # client label "assistant"
    agent: Agent
    driver: ModelDriver
    upload_dir: Path
    trace: Trace
    broker: ElicitationBroker
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def user_id(self) -> str:
        return self.principal.user_id

    def lock_for(self, conversation_id: str) -> asyncio.Lock:
        return self.locks.setdefault(conversation_id, asyncio.Lock())


@dataclass
class _Open:
    connection: MCPConnection
    closed: asyncio.Event
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    error: BaseException | None = None
    background: list[Any] = field(default_factory=list)   # coroutine functions run while the connection is open


class Registry:
    def __init__(self, settings: Settings, driver: ModelDriver, *, db: Database | None = None, upload_root: str | Path | None = None):
        self.settings = settings
        self.driver = driver
        self.db = db or database_for(settings)
        self.store = AccountStore(self.db)
        self.auth = Authenticator(settings, self.store)
        self.login_limiter = RateLimiter(limit=8, window=900)
        self.signup_limiter = RateLimiter(limit=20, window=900)
        self.upload_root = Path(upload_root or UPLOAD_ROOT)
        self.http_server = create_server(settings, db=self.db)  # multi-account: principal comes from the request
        self.contexts: dict[str, AppContext] = {}
        self._open_lock = asyncio.Lock()
        self._queue: asyncio.Queue[_Open | None] = asyncio.Queue()
        self._host: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ connection host

    async def start(self) -> None:
        self._host = asyncio.create_task(self._run_host(), name="finmcp-connection-host")

    async def _run_host(self) -> None:
        async with anyio.create_task_group() as tg:
            while True:
                item = await self._queue.get()
                if item is None:
                    break
                tg.start_soon(self._serve, item)

    @staticmethod
    async def _serve(item: _Open) -> None:
        try:
            async with item.connection, anyio.create_task_group() as tg:
                for fn in item.background:
                    tg.start_soon(fn)
                item.ready.set()
                await item.closed.wait()
                tg.cancel_scope.cancel()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the opener
            item.error = exc
            item.ready.set()

    async def _open(self, connection: MCPConnection, closed: asyncio.Event, background: list[Any] | None = None) -> None:
        if self._host is None or self._host.done():
            raise HTTPException(503, "API is shutting down")
        item = _Open(connection=connection, closed=closed, background=background or [])
        await self._queue.put(item)
        await item.ready.wait()
        if item.error is not None:
            raise item.error

    # ------------------------------------------------------------ accounts

    async def context_for(self, principal: Principal) -> AppContext:
        ctx = self.contexts.get(principal.user_id)
        if ctx is not None:
            return ctx
        async with self._open_lock:
            ctx = self.contexts.get(principal.user_id)
            if ctx is not None:
                return ctx
            profile = await anyio.to_thread.run_sync(self.store.get_profile, principal.user_id)
            if profile is None:
                profile = await anyio.to_thread.run_sync(self.store.upsert_profile, principal.user_id, principal.email, principal.name)
            settings = dataclasses.replace(self.settings, currency=profile.currency)
            closed = asyncio.Event()
            upload_dir = self.upload_root / profile.id
            upload_dir.mkdir(parents=True, exist_ok=True)
            trace, broker = Trace(profile.id), ElicitationBroker(profile.id)
            sampling = sampling_callback(self.driver)

            def connect(client: str) -> MCPConnection:
                server = create_server(settings, db=self.db, user_id=profile.id, client=client, currency=profile.currency)
                return MCPConnection.in_process(server, client_name=f"finmcp-{client}", trace=trace.record, sampling=sampling,
                                                elicitation=broker.callback(client), roots=roots_callback([upload_dir]))

            web, assistant = connect("web"), connect("assistant")
            await self._open(web, closed, [lambda: watch_resources(web, profile.id, list(ALL_RESOURCES))])
            await self._open(assistant, closed)
            agent = Agent(assistant, self.driver, currency=profile.currency)
            await agent.prepare()
            ctx = AppContext(principal=principal, profile=profile, settings=settings, connection=web, assistant=assistant, agent=agent,
                             driver=self.driver, upload_dir=upload_dir, trace=trace, broker=broker, closed=closed)
            self.contexts[profile.id] = ctx
            return ctx

    def forget(self, user_id: str) -> None:
        """Drop cached state for an account (after profile changes or deletion)."""
        ctx = self.contexts.pop(user_id, None)
        if ctx is not None:
            ctx.closed.set()
        self.http_server.finmcp.forget(user_id)  # type: ignore[attr-defined]
        self.auth.forget(user_id)
        buses.forget(user_id)

    async def close(self) -> None:
        for ctx in list(self.contexts.values()):
            ctx.closed.set()
        self.contexts.clear()
        if self._host is not None:
            await self._queue.put(None)
            with contextlib.suppress(Exception):  # best effort on shutdown
                await self._host
            self._host = None
        self.db.close()


# ------------------------------------------------------------------ dependencies


def get_registry(request: Request) -> Registry:
    reg = getattr(request.app.state, "registry", None)
    if reg is None:
        raise HTTPException(503, "API is starting up")
    return reg


def _token_from(request: Request) -> str | None:
    return bearer_from_header(request.headers.get("authorization"))


def current_principal(request: Request) -> Principal | None:
    reg = get_registry(request)
    token = _token_from(request)
    if not token:
        return None
    return reg.auth.principal(token, client="web")


def require_principal(request: Request) -> Principal:
    principal = current_principal(request)
    if principal is None:
        raise HTTPException(401, "Sign in to use your ledger.", headers={"WWW-Authenticate": "Bearer"})
    return principal


async def get_ctx(request: Request) -> AppContext:
    reg = get_registry(request)
    principal = await anyio.to_thread.run_sync(current_principal, request)
    if principal is None:
        raise HTTPException(401, "Sign in to use your ledger.", headers={"WWW-Authenticate": "Bearer"})
    return await reg.context_for(principal)


def _clean(message: str) -> str:
    # "Error executing tool list_transactions: start_date must be..." -> "start_date must be..."
    if message.startswith("Error executing tool "):
        _, _, rest = message.partition(": ")
        return rest or message
    return message


async def call_tool(ctx: AppContext, name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool on the account's 'web' connection and return its structured payload; tool errors become HTTP 400."""
    outcome = await ctx.connection.call_tool(name, arguments or {})
    if not outcome.ok:
        raise HTTPException(400, _clean(outcome.text))
    if outcome.data is not None:
        return outcome.data
    return {"text": outcome.text}
