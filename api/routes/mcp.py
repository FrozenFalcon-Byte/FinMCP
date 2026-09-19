"""The MCP inspector behind the app's MCP screen: the protocol trace, negotiated capabilities, the server's open
questions (elicitation) and a playground that calls tools, reads resources, renders prompts and completes arguments
through the account's own MCP client, so everything it shows is real protocol traffic."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from finmcp.subscriptions import ALL_RESOURCES

from ..deps import AppContext, Registry, get_ctx, get_registry

router = APIRouter(tags=["mcp"])


class Answer(BaseModel):
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None


class ToolCall(BaseModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class PromptGet(BaseModel):
    name: str = Field(min_length=1)
    arguments: dict[str, str] = Field(default_factory=dict)


def _session(conn: Any) -> dict[str, Any]:
    info = conn.client.server_info
    return {"client": conn.client_name, "protocol": conn.client.protocol_version, "offers": conn.offers,
            "server": {"name": getattr(info, "name", None), "version": getattr(info, "version", None)},
            "server_capabilities": conn.server_capabilities()}


@router.get("/mcp/overview")
async def overview(ctx: AppContext = Depends(get_ctx), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """Architecture at a glance: both in-process sessions, what each side negotiated, live subscriptions, counters."""
    return {
        "endpoint": f"{reg.settings.public_url}/mcp",
        "sessions": [_session(ctx.connection), _session(ctx.assistant)],
        "subscribed": list(ALL_RESOURCES),
        "sampling_model": getattr(ctx.driver, "model", None) if "sampling" in ctx.connection.offers else None,
        "stats": ctx.trace.stats(),
        "open_questions": ctx.broker.open(),
    }


@router.get("/mcp/trace")
async def trace(limit: int = 120, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"entries": ctx.trace.recent(max(1, min(limit, 300))), "stats": ctx.trace.stats()}


@router.get("/mcp/elicitations")
async def open_questions(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"questions": ctx.broker.open()}


@router.post("/mcp/elicitations/{qid}")
async def answer(qid: str, body: Answer, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    if not ctx.broker.answer(qid, body.action, body.content):
        raise HTTPException(404, "That question is no longer open.")
    return {"ok": True}


@router.get("/mcp/schema")
async def schema(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Full definitions for the playground: tool input schemas, prompt arguments, resource templates."""
    tools = await ctx.connection.list_tools(refresh=True)
    prompts = await ctx.connection.list_prompts()
    templates = await ctx.connection.list_resource_templates()
    resources = await ctx.connection.list_resources()
    return {
        "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
                   "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else {}} for t in tools],
        "prompts": [{"name": p.name, "description": p.description,
                     "arguments": [{"name": a.name, "description": a.description, "required": bool(a.required)} for a in (p.arguments or [])]}
                    for p in prompts],
        "resources": [{"uri": str(r.uri), "name": r.name, "description": r.description} for r in resources],
        "templates": [{"uri_template": getattr(t, "uri_template", None), "name": t.name, "description": t.description} for t in templates],
    }


@router.post("/mcp/call")
async def call(body: ToolCall, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    out = await ctx.connection.call_tool(body.name, body.arguments)
    return {"ok": out.ok, "data": out.data, "text": out.text if out.data is None or not out.ok else None, "ms": out.elapsed_ms}


@router.get("/mcp/read")
async def read(uri: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return {"uri": uri, "text": await ctx.connection.read_resource_text(uri)}
    except Exception as exc:  # noqa: BLE001 - unknown URI or template mismatch
        raise HTTPException(400, str(exc)) from exc


@router.post("/mcp/prompt")
async def prompt(body: PromptGet, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return {"name": body.name, "text": await ctx.connection.get_prompt_text(body.name, body.arguments)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@router.get("/mcp/complete")
async def complete(ref: Literal["prompt", "resource"], name: str, argument: str, value: str = "",
                   ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    if ref == "prompt":
        values = await ctx.connection.complete_prompt_argument(name, argument, value)
    else:
        values = await ctx.connection.complete_resource_argument(name, argument, value)
    return {"values": values}
