"""Server-sent events: the account's change feed, so the app updates the moment any client writes to the ledger."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from finmcp.db.events import events

from ..deps import AppContext, get_ctx

router = APIRouter(tags=["events"])
HEARTBEAT_S = 20


@router.get("/events")
async def stream_events(ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    async def gen() -> AsyncIterator[str]:
        yield f"event: hello\ndata: {json.dumps({'account': ctx.user_id, 'subscribers': events.subscribers(ctx.user_id) + 1})}\n\n"
        async with events.subscribe(ctx.user_id) as queue:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item.get("type") == "write":  # internal: resource-updated events arrive through the MCP subscription instead
                    continue
                yield f"event: {item.get('type', 'change')}\ndata: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
