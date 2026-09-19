"""OpenRouter as the model backend (https://openrouter.ai), through its OpenAI-compatible chat completions API.

FinMCP keeps conversation history, tool definitions and multimodal input in the Anthropic Messages shape internally;
this module translates that to and from OpenRouter's format so any model OpenRouter serves can drive the assistant
(with tool calls), answer MCP sampling requests, and do the server-side JSON tasks (categorising, text to SQL,
receipt and statement extraction).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


def api_key() -> str | None:
    return (os.environ.get("OPENROUTER_API_KEY") or "").strip() or None


def headers(key: str | None = None) -> dict[str, str]:
    key = key or api_key()
    if not key:
        raise PermissionError("OPENROUTER_API_KEY is not set in .env.")
    # Referer and title are optional attribution headers OpenRouter shows on its dashboard.
    return {"Authorization": f"Bearer {key}", "HTTP-Referer": os.environ.get("FINMCP_PUBLIC_URL", "http://localhost:5173"), "X-Title": "FinMCP"}


def status_message(code: int, body: str) -> str:
    try:
        detail = json.loads(body).get("error", {}).get("message") or body
    except (ValueError, AttributeError):
        detail = body
    detail = str(detail)[:240]
    if code == 401:
        return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in .env."
    if code == 402:
        return "OpenRouter says the account is out of credits."
    if code == 429:
        return "OpenRouter rate limit reached; try again in a moment."
    return f"OpenRouter error {code}: {detail}"


# ---------------------------------------------------------------------- format translation


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif b.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


def to_parts(content: Any) -> str | list[dict[str, Any]]:
    """Anthropic user content (a string or text/image/document blocks) to OpenAI content parts."""
    if isinstance(content, str):
        return content
    parts: list[dict[str, Any]] = []
    for b in content:
        t = b.get("type")
        src = b.get("source") or {}
        if t == "text":
            parts.append({"type": "text", "text": b.get("text", "")})
        elif t == "image" and src.get("type") == "base64":
            parts.append({"type": "image_url", "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
        elif t == "document" and src.get("type") == "base64":
            parts.append({"type": "file", "file": {"filename": "document.pdf", "file_data": f"data:{src['media_type']};base64,{src['data']}"}})
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


def to_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic history (text, tool_use, tool_result blocks) to OpenAI chat messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                     for b in content if b.get("type") == "tool_use"]
            msg: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        rest = []
        for b in content:  # tool results must directly follow the assistant turn that asked for them
            if b.get("type") == "tool_result":
                text = _block_text(b.get("content"))
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": ("ERROR: " + text) if b.get("is_error") else text})
            else:
                rest.append(b)
        if rest:
            out.append({"role": "user", "content": to_parts(rest)})
    return out


def to_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}} for t in tools]


def parse_json(text: str, model: type[BaseModel]) -> BaseModel:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("the model returned no JSON object")
    try:
        return model.model_validate_json(match.group(0))
    except ValidationError as exc:
        raise ValueError(f"the model's JSON did not match {model.__name__}: {exc.errors()[0].get('msg')}") from exc


def complete_json(*, model: str, system: str, user: Any, output: type[BaseModel], max_tokens: int, timeout: float) -> BaseModel:
    """One non-streaming completion that must come back as a JSON object matching `output`."""
    schema = json.dumps(output.model_json_schema())
    body = {
        "model": model, "max_tokens": max_tokens, "temperature": 0,
        "messages": [{"role": "system", "content": f"{system}\n\nReply with exactly one JSON object matching this JSON schema and nothing else:\n{schema}"},
                     {"role": "user", "content": to_parts(user)}],
    }
    r = httpx.post(URL, json=body, headers=headers(), timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(status_message(r.status_code, r.text))
    data = r.json()
    if data.get("error"):
        raise RuntimeError(status_message(int(data["error"].get("code") or 500), json.dumps(data)))
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return parse_json(text, output)


__all__ = ["DEFAULT_MODEL", "URL", "api_key", "complete_json", "headers", "parse_json", "status_message", "to_messages", "to_parts", "to_tools"]
