"""The client side of MCP: one connection to FinMCP over stdio, streamable HTTP, or in-process.

Beyond tools, a connection can offer the server the client-side halves of the protocol: sampling (the server
borrows the client's model), elicitation (the server asks the user a question), roots (which files the server may
read), and it receives logging, progress and resource-updated notifications. Every request, response and
notification that crosses the connection can be reported to a `trace` callback, which is how the app shows the
protocol at work.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mcp.types as mt
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.subscriptions import ResourceUpdated

TraceFn = Callable[[dict[str, Any]], None]


@dataclass
class ToolOutcome:
    ok: bool
    text: str
    content: list[dict[str, Any]] = field(default_factory=list)   # Anthropic tool_result content blocks
    data: Any = None                                              # structured content if the tool returned any
    elapsed_ms: int = 0


def _content_to_anthropic(blocks: list[Any]) -> tuple[list[dict[str, Any]], str]:
    out: list[dict[str, Any]] = []
    texts: list[str] = []
    for b in blocks or []:
        t = getattr(b, "type", None)
        if t == "text":
            out.append({"type": "text", "text": b.text})
            texts.append(b.text)
        elif t == "image":
            out.append({"type": "image", "source": {"type": "base64", "media_type": b.mime_type, "data": b.data}})
            texts.append(f"[image {b.mime_type}]")
        elif t == "resource":
            res = getattr(b, "resource", None)
            text = getattr(res, "text", None)
            if text is not None:
                out.append({"type": "text", "text": text})
                texts.append(text)
            else:
                out.append({"type": "text", "text": f"[binary resource {getattr(res, 'uri', '')}]"})
        else:
            out.append({"type": "text", "text": str(b)})
    return out, "\n".join(texts)


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(_text_of(c) for c in content)
    return str(getattr(content, "text", "") or "")


class MCPConnection:
    """Usage: `async with MCPConnection.in_process(server) as conn: await conn.call_tool(...)`."""

    def __init__(self, target: Any, *, label: str = "finmcp", client_name: str = "finmcp-agent", version: str = "1.0",
                 sampling: Callable[..., Awaitable[Any]] | None = None, elicitation: Callable[..., Awaitable[Any]] | None = None,
                 roots: Callable[..., Awaitable[Any]] | None = None, trace: TraceFn | None = None):
        self.target = target
        self.label = label
        self.client_name = client_name
        self.version = version
        self._sampling = sampling
        self._elicitation = elicitation
        self._roots = roots
        self._trace = trace
        self._client: Client | None = None
        self._tools: list[mt.Tool] | None = None
        self.seq = 0

    # ------------------------------------------------------------ constructors

    @classmethod
    def in_process(cls, server: Any, **kw: Any) -> MCPConnection:
        return cls(server, label="in-process", **kw)

    @classmethod
    def http(cls, url: str, headers: dict[str, str] | None = None, http_client: Any = None, **kw: Any) -> MCPConnection:
        """Streamable HTTP. Pass `headers` (e.g. a bearer token) or a ready `httpx2.AsyncClient`."""
        if headers or http_client is not None:
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared._httpx_utils import create_mcp_http_client

            client = http_client or create_mcp_http_client(headers=headers)
            return cls(streamable_http_client(url, http_client=client), label=url, **kw)
        return cls(url, label=url, **kw)

    @classmethod
    def stdio(cls, *, python: str | None = None, root: str | Path | None = None, args: tuple[str, ...] = (), env: dict[str, str] | None = None,
              **kw: Any) -> MCPConnection:
        root = Path(root or Path(__file__).resolve().parent.parent)
        python = python or str(root / ".venv" / "bin" / "python")
        merged = {**os.environ, "PYTHONPATH": str(root), **(env or {})}
        params = StdioServerParameters(command=python, args=["-m", "finmcp", *args], cwd=str(root), env=merged)
        return cls(params, label=f"stdio:{python} -m finmcp {' '.join(args)}", **kw)

    # ------------------------------------------------------------ tracing

    def record(self, method: str, *, kind: str, detail: str = "", ok: bool = True, ms: int | None = None, direction: str = "out",
               **extra: Any) -> None:
        if self._trace is None:
            return
        self.seq += 1
        entry = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "client": self.client_name, "dir": direction,
                 "method": method, "kind": kind, "detail": detail[:200], "ok": ok, "ms": ms, **extra}
        self._trace(entry)

    # ------------------------------------------------------------ lifecycle

    async def __aenter__(self) -> MCPConnection:
        t0 = time.perf_counter()
        self._client = Client(
            self.target,
            client_info=mt.Implementation(name=self.client_name, version=self.version),
            sampling_callback=self._wrap_sampling() if self._sampling else None,
            elicitation_callback=self._wrap_elicitation() if self._elicitation else None,
            list_roots_callback=self._wrap_roots() if self._roots else None,
            logging_callback=self._on_log,
            log_level="info",  # the server only sends log notifications at or above the level the client asks for
        )
        await self._client.__aenter__()
        info = self._client.server_info
        self.record("initialize", kind="session", detail=f"{getattr(info, 'name', '?')} {getattr(info, 'version', '')}".strip(),
                    ms=int((time.perf_counter() - t0) * 1000), offers=self.offers)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError("MCPConnection is not open; use `async with`.")
        return self._client

    @property
    def instructions(self) -> str | None:
        return self.client.instructions

    @property
    def server_name(self) -> str | None:
        info = self.client.server_info
        return getattr(info, "name", None) if info else None

    @property
    def offers(self) -> list[str]:
        """Client-side capabilities this connection declared to the server."""
        out = []
        if self._sampling:
            out.append("sampling")
        if self._elicitation:
            out.append("elicitation")
        if self._roots:
            out.append("roots")
        return out

    def server_capabilities(self) -> dict[str, Any]:
        caps = self.client.server_capabilities
        if caps is None:
            return {}
        return {k: True for k, v in caps.model_dump(exclude_none=True).items() if v is not None and v != {}} | {
            k: v for k, v in caps.model_dump(exclude_none=True).items() if isinstance(v, dict) and v}

    # ------------------------------------------------------------ client-side handlers

    def _wrap_sampling(self) -> Callable[..., Awaitable[Any]]:
        async def handler(context: Any, params: mt.CreateMessageRequestParams) -> Any:
            t0 = time.perf_counter()
            assert self._sampling is not None
            result = await self._sampling(context, params)
            ok = not isinstance(result, mt.ErrorData)
            preview = _text_of(getattr(result, "content", None))[:80] if ok else str(getattr(result, "message", ""))[:80]
            self.record("sampling/createMessage", kind="sampling", direction="in", ok=ok, ms=int((time.perf_counter() - t0) * 1000),
                        detail=f"{len(params.messages)} message(s) -> {preview}")
            return result
        return handler

    def _wrap_elicitation(self) -> Callable[..., Awaitable[Any]]:
        async def handler(context: Any, params: Any) -> Any:
            t0 = time.perf_counter()
            assert self._elicitation is not None
            result = await self._elicitation(context, params)
            action = getattr(result, "action", "error")
            self.record("elicitation/create", kind="elicitation", direction="in", ok=action == "accept", ms=int((time.perf_counter() - t0) * 1000),
                        detail=f"{str(getattr(params, 'message', ''))[:90]} -> {action}")
            return result
        return handler

    def _wrap_roots(self) -> Callable[..., Awaitable[Any]]:
        async def handler(context: Any) -> Any:
            assert self._roots is not None
            result = await self._roots(context)
            roots = getattr(result, "roots", []) or []
            self.record("roots/list", kind="roots", direction="in", detail=", ".join(str(r.name or r.uri) for r in roots))
            return result
        return handler

    async def _on_log(self, params: mt.LoggingMessageNotificationParams) -> None:
        data = params.data if isinstance(params.data, str) else json.dumps(params.data, default=str)
        self.record("notifications/message", kind="log", direction="in", detail=data, level=params.level)

    # ------------------------------------------------------------ tools

    async def list_tools(self, refresh: bool = False) -> list[mt.Tool]:
        if self._tools is None or refresh:
            t0 = time.perf_counter()
            listing = await self.client.list_tools()
            self._tools = list(getattr(listing, "tools", listing))
            self.record("tools/list", kind="tool", detail=f"{len(self._tools)} tools", ms=int((time.perf_counter() - t0) * 1000))
        return self._tools

    @staticmethod
    def to_anthropic_tools(tools: list[mt.Tool]) -> list[dict[str, Any]]:
        out = []
        for t in tools:
            schema = t.input_schema if isinstance(t.input_schema, dict) else dict(t.input_schema or {})
            out.append({"name": t.name, "description": t.description or "", "input_schema": schema})
        return out

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None,
                        progress: Callable[[float, float | None, str | None], Awaitable[None]] | None = None) -> ToolOutcome:
        t0 = time.perf_counter()

        async def on_progress(value: float, total: float | None, message: str | None) -> None:
            self.record("notifications/progress", kind="progress", direction="in", detail=f"{name}: {message or ''} {value:g}/{total or '?'}",
                        progress=value, total=total, tool=name)
            if progress is not None:
                await progress(value, total, message)

        try:
            result = await self.client.call_tool(name, arguments or {}, progress_callback=on_progress)
        except Exception as exc:  # transport or protocol failure
            ms = int((time.perf_counter() - t0) * 1000)
            self.record("tools/call", kind="tool", detail=name, ok=False, ms=ms, error=f"{type(exc).__name__}: {exc}"[:200])
            return ToolOutcome(ok=False, text=f"{type(exc).__name__}: {exc}", content=[{"type": "text", "text": f"Tool call failed: {exc}"}], elapsed_ms=ms)
        elapsed = int((time.perf_counter() - t0) * 1000)
        content, text = _content_to_anthropic(getattr(result, "content", []) or [])
        data = getattr(result, "structured_content", None)
        is_error = bool(getattr(result, "is_error", False))
        if not content:
            content = [{"type": "text", "text": json.dumps(data) if data is not None else "(no output)"}]
            text = content[0]["text"]
        self.record("tools/call", kind="tool", detail=name, ok=not is_error, ms=elapsed, args=_short_args(arguments),
                    error=text[:160] if is_error else None)
        return ToolOutcome(ok=not is_error, text=text, content=content, data=data, elapsed_ms=elapsed)

    # ------------------------------------------------------------ resources / prompts / completion

    async def read_resource_text(self, uri: str) -> str:
        t0 = time.perf_counter()
        res = await self.client.read_resource(uri)
        parts = [getattr(c, "text", "") for c in getattr(res, "contents", [])]
        text = "\n".join(p for p in parts if p)
        self.record("resources/read", kind="resource", detail=uri, ms=int((time.perf_counter() - t0) * 1000), bytes=len(text))
        return text

    async def read_resource_json(self, uri: str) -> Any:
        return json.loads(await self.read_resource_text(uri))

    async def list_resources(self) -> list[mt.Resource]:
        result = await self.client.list_resources()
        out = list(getattr(result, "resources", result))
        self.record("resources/list", kind="resource", detail=f"{len(out)} resources")
        return out

    async def list_resource_templates(self) -> list[Any]:
        result = await self.client.list_resource_templates()
        return list(getattr(result, "resource_templates", getattr(result, "resourceTemplates", result)))

    async def list_prompts(self) -> list[mt.Prompt]:
        listing = await self.client.list_prompts()
        out = list(getattr(listing, "prompts", listing))
        self.record("prompts/list", kind="prompt", detail=f"{len(out)} prompts")
        return out

    async def get_prompt_text(self, name: str, arguments: dict[str, str] | None = None) -> str:
        t0 = time.perf_counter()
        res = await self.client.get_prompt(name, arguments or {})
        texts = []
        for m in getattr(res, "messages", []):
            c = m.content
            texts.append(getattr(c, "text", "") if not isinstance(c, list) else "\n".join(getattr(x, "text", "") for x in c))
        self.record("prompts/get", kind="prompt", detail=name, ms=int((time.perf_counter() - t0) * 1000))
        return "\n".join(texts)

    async def complete_prompt_argument(self, prompt: str, argument: str, value: str) -> list[str]:
        t0 = time.perf_counter()
        res = await self.client.complete(mt.PromptReference(type="ref/prompt", name=prompt), {"name": argument, "value": value})
        values = list(res.completion.values)
        self.record("completion/complete", kind="completion", detail=f"{prompt}.{argument}={value!r} -> {len(values)}", ms=int((time.perf_counter() - t0) * 1000))
        return values

    async def complete_resource_argument(self, template: str, argument: str, value: str) -> list[str]:
        t0 = time.perf_counter()
        res = await self.client.complete(mt.ResourceTemplateReference(type="ref/resource", uri=template), {"name": argument, "value": value})
        values = list(res.completion.values)
        self.record("completion/complete", kind="completion", detail=f"{template}.{argument}={value!r} -> {len(values)}", ms=int((time.perf_counter() - t0) * 1000))
        return values

    # ------------------------------------------------------------ subscriptions

    async def listen(self, uris: list[str]) -> AsyncIterator[str]:
        """Open a `subscriptions/listen` stream and yield the URI of every resource-updated event."""
        async with self.client.listen(resource_subscriptions=uris) as sub:
            self.record("subscriptions/listen", kind="subscription", detail=", ".join(uris), subscription=str(sub.subscription_id))
            async for event in sub:
                if isinstance(event, ResourceUpdated):
                    self.record("notifications/resources/updated", kind="subscription", direction="in", detail=event.uri, uri=event.uri)
                    yield event.uri


def _short_args(arguments: dict[str, Any] | None) -> dict[str, Any] | None:
    if not arguments:
        return None
    out: dict[str, Any] = {}
    for k, v in list(arguments.items())[:8]:
        out[k] = v if isinstance(v, int | float | bool) or v is None else str(v)[:60]
    return out
