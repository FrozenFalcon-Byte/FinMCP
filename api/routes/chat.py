from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..deps import AppContext, get_ctx

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(default=None, max_length=64)


@router.post("/chat")
async def chat(body: ChatRequest, ctx: AppContext = Depends(get_ctx)):
    conv = ctx.agent.conversation(body.conversation_id)
    lock = ctx.lock_for(conv.id)
    if lock.locked():
        raise HTTPException(409, "This conversation is already answering; wait for it to finish.")

    async def stream():
        async with lock:
            yield json.dumps({"type": "conversation", "conversation_id": conv.id}) + "\n"
            async for ev in ctx.agent.run(body.message, conv.id):
                yield json.dumps(ev, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/chat/{conversation_id}")
async def transcript(conversation_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    conv = ctx.agent.conversations.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    return {"conversation_id": conv.id, "title": conv.title, "turns": conv.turns, "created_at": conv.created_at,
            "updated_at": conv.updated_at, "messages": ctx.agent.transcript(conv.id)}


@router.get("/chats")
async def list_conversations(ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    return [{"conversation_id": c.id, "title": c.title, "turns": c.turns, "updated_at": c.updated_at}
            for c in sorted(ctx.agent.conversations.values(), key=lambda c: c.updated_at, reverse=True)]


@router.delete("/chat/{conversation_id}")
async def reset(conversation_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"reset": ctx.agent.reset(conversation_id)}


@router.get("/prompts")
async def prompts(ctx: AppContext = Depends(get_ctx)) -> list[dict[str, Any]]:
    out = []
    for p in await ctx.connection.list_prompts():
        args = [{"name": a.name, "description": a.description, "required": bool(a.required)} for a in (p.arguments or [])]
        out.append({"name": p.name, "title": getattr(p, "title", None) or p.name, "description": p.description, "arguments": args})
    return out


class RenderPrompt(BaseModel):
    arguments: dict[str, str] = Field(default_factory=dict)


@router.post("/prompts/{name}")
async def render_prompt(name: str, body: RenderPrompt, ctx: AppContext = Depends(get_ctx)) -> dict[str, str]:
    try:
        text = await ctx.connection.get_prompt_text(name, body.arguments)
    except Exception as exc:
        raise HTTPException(404, f"prompt {name!r} not available: {exc}") from exc
    return {"name": name, "text": text}
