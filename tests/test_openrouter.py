"""OpenRouter backend: format translation, the streaming driver (tool calls included) and the JSON provider,
against a mocked OpenRouter so no key or network is needed."""
from __future__ import annotations

import json

import httpx
import pytest

from agent.drivers import OpenRouterDriver, make_driver
from finmcp.llm import openrouter
from finmcp.llm.provider import CategoryGuess, OpenRouterProvider, get_provider


def test_history_translation():
    msgs = openrouter.to_messages("sys", [
        {"role": "user", "content": "how much on food?"},
        {"role": "assistant", "content": [{"type": "text", "text": "Checking."},
                                          {"type": "tool_use", "id": "t1", "name": "get_summary", "input": {"period": "last month"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "{\"spent\": 10}"}]},
                                     {"type": "text", "text": "thanks"}]},
    ])
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "user"]
    assert msgs[2]["tool_calls"][0]["function"] == {"name": "get_summary", "arguments": "{\"period\": \"last month\"}"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": "{\"spent\": 10}"}
    img = openrouter.to_parts([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}}])
    assert img == [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]
    tools = openrouter.to_tools([{"name": "x", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
    assert tools[0]["function"]["parameters"]["type"] == "object"


def _sse(*chunks: dict) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + ": OPENROUTER PROCESSING\n\ndata: [DONE]\n\n").encode()


@pytest.fixture
def mock_openrouter(monkeypatch):
    seen: list[dict] = []

    def install(body: bytes, status: int = 200):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            assert request.headers["authorization"] == "Bearer sk-or-test"
            return httpx.Response(status, content=body)

        real = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
        monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw))

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    install.seen = seen  # type: ignore[attr-defined]
    return install


async def test_driver_streams_text_and_tool_calls(mock_openrouter):
    mock_openrouter(_sse(
        {"model": "anthropic/claude-haiku-4.5", "choices": [{"delta": {"content": "Let me "}}]},
        {"choices": [{"delta": {"content": "check."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "get_summary", "arguments": "{\"per"}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "iod\": \"last month\"}"}}]}, "finish_reason": "tool_calls"}]},
    ))
    events = [e async for e in OpenRouterDriver("anthropic/claude-haiku-4.5").stream(
        system="s", messages=[{"role": "user", "content": "hi"}], tools=[{"name": "get_summary", "description": "", "input_schema": {"type": "object"}}])]
    assert "".join(e["text"] for e in events if e["type"] == "text_delta") == "Let me check."
    final = events[-1]["final"]
    assert final.stop_reason == "tool_use" and final.model == "anthropic/claude-haiku-4.5"
    assert final.content == [{"type": "text", "text": "Let me check."},
                             {"type": "tool_use", "id": "call_1", "name": "get_summary", "input": {"period": "last month"}}]
    assert mock_openrouter.seen[0]["stream"] is True and mock_openrouter.seen[0]["tools"][0]["type"] == "function"


async def test_driver_reports_bad_key(mock_openrouter):
    from agent.drivers import DriverError

    mock_openrouter(b'{"error": {"message": "No auth credentials found", "code": 401}}', status=401)
    with pytest.raises(DriverError, match="OPENROUTER_API_KEY"):
        [e async for e in OpenRouterDriver("m").stream(system="", messages=[{"role": "user", "content": "hi"}], tools=[])]


def test_provider_parses_json(mock_openrouter):
    reply = {"choices": [{"message": {"content": "Sure: {\"category\": \"Shopping\", \"confidence\": 0.9, \"reasoning\": \"retail\"}"}}]}
    mock_openrouter(json.dumps(reply).encode())
    guess = OpenRouterProvider("m")._parse(system="s", user="u", output_format=CategoryGuess, effort="low")
    assert guess.category == "Shopping" and guess.confidence == 0.9
    assert "JSON schema" in mock_openrouter.seen[0]["messages"][0]["content"]


def test_backend_selection(monkeypatch):
    from finmcp.config import load_settings

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    live = load_settings(llm_mode="auto")
    assert live.llm_backend == "openrouter" and live.model == "openai/gpt-4o-mini" and live.use_llm
    assert get_provider(live).name == "openrouter"
    assert make_driver("auto", model=live.model, backend=live.llm_backend).name == "openrouter"
    assert make_driver("auto", backend="none").name == "local"
