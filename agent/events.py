"""Event protocol emitted by the agent while it works. Every event is a plain dict so it can go over SSE as-is."""
from __future__ import annotations

from typing import Any


def text_delta(text: str) -> dict[str, Any]:
    return {"type": "text_delta", "text": text}


def tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_call", "id": call_id, "name": name, "input": arguments}


def tool_result(call_id: str, name: str, ok: bool, preview: str, elapsed_ms: int, data: Any = None) -> dict[str, Any]:
    return {"type": "tool_result", "id": call_id, "name": name, "ok": ok, "preview": preview, "elapsed_ms": elapsed_ms, "data": data}


def status(message: str) -> dict[str, Any]:
    return {"type": "status", "message": message}


def error(message: str, *, fatal: bool = False) -> dict[str, Any]:
    return {"type": "error", "message": message, "fatal": fatal}


def done(text: str, *, conversation_id: str, iterations: int, stop_reason: str | None, usage: dict[str, Any] | None) -> dict[str, Any]:
    return {"type": "done", "text": text, "conversation_id": conversation_id, "iterations": iterations,
            "stop_reason": stop_reason, "usage": usage}
