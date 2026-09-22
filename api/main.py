"""FinMCP API: a thin FastAPI layer over per-account MCP connections, plus the remote MCP endpoint at /mcp.
It never touches ledger tables directly; every ledger read or write is an MCP tool call."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from agent.drivers import make_driver
from finmcp import __version__
from finmcp.config import ROOT, load_settings
from finmcp.db.accounts import Principal

from .deps import Registry, current_principal, get_registry
from .mcp_http import build_mcp_app, run_session_manager
from .routes import auth, chat, connect, events, imports, ledger, mcp, passkeys

log = logging.getLogger("finmcp.api")
WEB_DIST = ROOT / "web" / "dist"

DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def cors_origins() -> list[str]:
    """Browser origins allowed to call this API. The frontend is deployed separately (Vercel), so its origin
    has to be named here: FINMCP_CORS_ORIGINS, comma separated. Dev origins are always allowed."""
    extra = [o.strip().rstrip("/") for o in os.environ.get("FINMCP_CORS_ORIGINS", "").split(",") if o.strip()]
    return list(dict.fromkeys([*DEV_ORIGINS, *extra]))


class _MountedMCP:
    """Forwards /mcp to the MCP app built in the lifespan (the registry does not exist at import time)."""

    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        target = getattr(self.app.state, "mcp_app", None)
        if target is None:
            response = JSONResponse({"detail": "MCP endpoint is starting"}, status_code=503)
            await response(scope, receive, send)
            return
        await target(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    driver = make_driver(os.environ.get("FINMCP_AGENT_DRIVER", "auto"), model=settings.model,
                         effort=os.environ.get("FINMCP_AGENT_EFFORT", "medium"), fallbacks=settings.fallbacks,
                         backend=settings.llm_backend)
    registry = Registry(settings, driver)
    await registry.start()
    app.state.registry = registry
    app.state.mcp_app = build_mcp_app(registry, public_url=settings.public_url)
    log.info("FinMCP API ready: auth=%s database=%s rls=%s driver=%s accounts=%d mcp=%s/mcp", settings.auth_mode,
             "supabase" if settings.supabase_configured else "local", registry.db.rls, driver.name, registry.store.count_profiles(),
             settings.public_url)
    try:
        async with run_session_manager(registry):
            yield
    finally:
        app.state.mcp_app = None
        await registry.close()


def create_app() -> FastAPI:
    app = FastAPI(title="FinMCP API", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_origin_regex=os.environ.get("FINMCP_CORS_ORIGIN_REGEX") or None,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["mcp-session-id", "mcp-protocol-version"])
    app.include_router(auth.router, prefix="/api")
    app.include_router(passkeys.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(ledger.router, prefix="/api")
    app.include_router(imports.router, prefix="/api")
    app.include_router(connect.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(mcp.router, prefix="/api")

    @app.get("/api/health")
    async def health(request: Request, principal: Principal | None = Depends(current_principal)) -> Any:
        reg = getattr(request.app.state, "registry", None)
        if reg is None:
            return JSONResponse({"ok": False, "status": "starting"}, status_code=503)
        s = reg.settings
        out: dict[str, Any] = {
            "ok": True, "version": __version__, "driver": reg.driver.name,
            "model": s.model if reg.driver.name in {"anthropic", "openrouter"} else None,
            "auth_mode": reg.auth.mode, "database": "supabase" if s.supabase_configured else "local", "rls": reg.db.rls,
            "accounts": reg.store.count_profiles(), "authenticated": principal is not None,
            "mcp_endpoint": f"{s.public_url}/mcp",
        }
        if principal is not None:
            ctx = await reg.context_for(principal)
            out.update({"mcp": ctx.connection.label, "tools": len(ctx.agent.tools),
                        "status": await ctx.connection.read_resource_json("finmcp://status"), "user": ctx.profile.public()})
        return out

    app.add_route("/mcp", _MountedMCP(app), methods=["GET", "POST", "DELETE"], name="mcp")

    if (WEB_DIST / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = WEB_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("FINMCP_API_HOST", "127.0.0.1")
    port = int(os.environ.get("FINMCP_API_PORT", "8000"))
    uvicorn.run("api.main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()


__all__ = ["app", "create_app", "get_registry"]
