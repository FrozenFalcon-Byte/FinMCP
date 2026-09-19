"""The remote MCP endpoint: Streamable HTTP at /mcp, one server for every account.

Every request must carry `Authorization: Bearer <token>` where the token is a personal MCP token (fm_...) created in
the app, or a signed-in session's JWT. The middleware resolves it to a principal and publishes it through the same
context variables the MCP SDK uses, so tools and resources know whose ledger they are working on.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from finmcp.server import current_principal

from .auth import bearer_from_header
from .deps import Registry

log = logging.getLogger("finmcp.api.mcp")


async def _reject(send: Send, status: int, message: str) -> None:
    body = json.dumps({"error": "unauthorized", "detail": message}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
        (b"www-authenticate", b'Bearer realm="finmcp", error="invalid_token"'),
    ]})
    await send({"type": "http.response.body", "body": body})


class MCPBearerAuth:
    """ASGI middleware: bearer token -> principal, attached to the request scope and to the context variables."""

    def __init__(self, app: ASGIApp, registry: Registry):
        self.app = app
        self.registry = registry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = bearer_from_header(Headers(scope=scope).get("authorization"))
        if not token:
            await _reject(send, 401, "This MCP endpoint needs a bearer token. Create one under Connect in the FinMCP app.")
            return
        principal = await anyio.to_thread.run_sync(lambda: self.registry.auth.principal(token, client="mcp"))
        if principal is None:
            await _reject(send, 401, "That token is not valid or was revoked.")
            return
        scope.setdefault("state", {})["principal"] = principal
        access = AccessToken(token=token, client_id=principal.user_id, scopes=["ledger"], subject=principal.user_id,
                             claims={"email": principal.email, "via": principal.via})
        t1 = current_principal.set(principal)
        t2 = auth_context_var.set(AuthenticatedUser(access))
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(t1)
            auth_context_var.reset(t2)


def build_mcp_app(registry: Registry, *, public_url: str) -> Any:
    """The Starlette sub-app to mount at /mcp, plus its session-manager lifespan."""
    host = "0.0.0.0"  # the API is reachable by whatever host name the user chose; do not enable localhost-only DNS rebinding rules
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    inner = registry.http_server.streamable_http_app(streamable_http_path="/mcp", host=host, transport_security=security, json_response=False)
    return MCPBearerAuth(inner, registry)


@asynccontextmanager
async def run_session_manager(registry: Registry) -> AsyncIterator[None]:
    """Sub-app lifespans do not run when mounted inside FastAPI, so the API's lifespan drives the session manager."""
    manager = registry.http_server._lowlevel_server._session_manager  # noqa: SLF001 - created by streamable_http_app()
    if manager is None:
        yield
        return
    async with manager.run():
        yield
