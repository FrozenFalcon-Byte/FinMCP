"""Connect: personal MCP tokens, the tool catalogue and which clients have been using the ledger."""
from __future__ import annotations

import asyncio
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from finmcp import __version__
from finmcp.db.accounts import Principal
from finmcp.server import create_server

from ..deps import AppContext, Registry, call_tool, get_ctx, get_registry, require_principal

router = APIRouter(tags=["connect"])

_public_catalog: dict[str, Any] | None = None


def _tool_row(t: Any) -> dict[str, Any]:
    ann = getattr(t, "annotations", None)
    return {"name": t.name, "title": getattr(t, "title", None), "description": t.description,
            "read_only": bool(getattr(ann, "read_only_hint", False)), "destructive": bool(getattr(ann, "destructive_hint", False))}


@router.get("/mcp/public-catalog")
async def public_catalog(reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """The protocol surface with no account attached: what any client sees the moment it connects. Metadata only —
    building the server does not touch the ledger — so the public docs page can render the real thing."""
    global _public_catalog
    if _public_catalog is None:
        server = create_server(reg.settings)
        tools, resources, templates, prompts = await asyncio.gather(
            server.list_tools(), server.list_resources(), server.list_resource_templates(), server.list_prompts())
        _public_catalog = {
            "server": {"name": "finmcp", "version": __version__},
            "tools": [_tool_row(t) for t in tools],
            "resources": [{"uri": str(r.uri), "name": r.name, "description": r.description} for r in resources],
            "templates": [{"uri_template": t.uri_template, "name": t.name, "description": t.description} for t in templates],
            "prompts": [{"name": p.name, "title": getattr(p, "title", None) or p.name, "description": p.description} for p in prompts],
        }
    return {**_public_catalog, "endpoint": f"{reg.settings.public_url}/mcp"}


class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.get("/mcp/tokens")
async def list_tokens(principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> list[dict[str, Any]]:
    return await anyio.to_thread.run_sync(reg.store.list_tokens, principal.user_id)


@router.post("/mcp/tokens", status_code=201)
async def create_token(body: TokenBody, principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    token, record = await anyio.to_thread.run_sync(reg.store.create_token, principal.user_id, body.name)
    return {"token": token, "record": record, "endpoint": f"{reg.settings.public_url}/mcp"}


@router.delete("/mcp/tokens/{token_id}")
async def revoke_token(token_id: str, principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    ok = await anyio.to_thread.run_sync(reg.store.revoke_token, principal.user_id, token_id)
    if not ok:
        raise HTTPException(404, "Token not found")
    return {"revoked": True}


@router.get("/mcp/catalog")
async def catalog(ctx: AppContext = Depends(get_ctx), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """What an MCP host sees when it connects: tools, resources and prompts, with descriptions."""
    tools = await ctx.connection.list_tools(refresh=True)
    resources = await ctx.connection.list_resources()
    prompts = await ctx.connection.list_prompts()
    return {
        "endpoint": f"{reg.settings.public_url}/mcp",
        "server": {"name": "finmcp", "instructions": ctx.connection.instructions},
        "tools": [{"name": t.name, "title": getattr(t, "title", None), "description": t.description,
                   "read_only": bool(getattr(getattr(t, "annotations", None), "read_only_hint", False)),
                   "destructive": bool(getattr(getattr(t, "annotations", None), "destructive_hint", False))} for t in tools],
        "resources": [{"uri": str(r.uri), "name": r.name, "description": r.description} for r in resources],
        "prompts": [{"name": p.name, "title": getattr(p, "title", None) or p.name, "description": p.description} for p in prompts],
    }


@router.get("/mcp/clients")
async def clients(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    data = await call_tool(ctx, "recent_activity", {"limit": 1})
    return {"clients": data.get("clients", [])}
