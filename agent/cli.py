"""Terminal chat with the FinMCP agent: `finmcp-agent` or `python -m agent.cli`."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any

from finmcp.config import load_settings

from .drivers import make_driver
from .mcp_client import MCPConnection
from .orchestrator import Agent

TTY = sys.stdout.isatty()


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if TTY else text


def build_connection(args: argparse.Namespace, settings: Any) -> MCPConnection:
    if args.server == "http":
        headers = {"Authorization": f"Bearer {args.token}"} if args.token else None
        return MCPConnection.http(args.url or "http://127.0.0.1:8000/mcp", headers=headers)
    if args.server == "stdio":
        extra = ["--llm", settings.llm_mode, "--client", "cli"]
        if settings.seed_if_empty:
            extra.append("--seed-if-empty")
        if args.token:
            extra += ["--token", args.token]
        if args.user_email:
            extra += ["--user-email", args.user_email]
        return MCPConnection.stdio(args=tuple(extra))
    from finmcp.__main__ import resolve_principal
    from finmcp.db import database_for
    from finmcp.server import create_server, seed_account

    db = database_for(settings)
    principal = resolve_principal(settings, db, token=args.token, email=args.user_email)
    server = create_server(settings, db=db, user_id=principal.user_id, client="cli")
    if settings.seed_if_empty:
        seed_account(server, only_if_empty=True)
    return MCPConnection.in_process(server)


async def chat(args: argparse.Namespace) -> int:
    settings = load_settings(llm_mode=args.llm, seed_if_empty=args.seed_if_empty)
    driver = make_driver(args.driver, model=args.model or settings.model, effort=args.effort, fallbacks=settings.fallbacks,
                         backend=settings.llm_backend)
    conn = build_connection(args, settings)
    async with conn:
        agent = Agent(conn, driver, currency=settings.currency, max_iterations=args.max_iterations)
        await agent.prepare()
        print(c("2", f"FinMCP agent · driver={driver.name} · server={conn.label} · {len(agent.tools)} tools · /tools /reset /quit"))
        if driver.name == "local":
            print(c("33", "No OPENROUTER_API_KEY set: answers come from FinMCP's built-in query engine. Add a key to .env for a real model."))
        conversation_id: str | None = None
        while True:
            try:
                line = await asyncio.to_thread(input, c("1;36", "you> "))
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            line = line.strip()
            if not line:
                continue
            if line in {"/quit", "/exit", "/q"}:
                return 0
            if line == "/reset":
                if conversation_id:
                    agent.reset(conversation_id)
                conversation_id = None
                print(c("2", "conversation cleared"))
                continue
            if line == "/tools":
                for t in agent.tools:
                    print(c("2", f"  {t['name']:24s} {t['description'][:90]}"))
                continue
            sys.stdout.write(c("1;32", "finmcp> "))
            sys.stdout.flush()
            async for ev in agent.run(line, conversation_id):
                t = ev["type"]
                if t == "text_delta":
                    sys.stdout.write(ev["text"])
                    sys.stdout.flush()
                elif t == "tool_call":
                    sys.stdout.write("\n" + c("2", f"  -> {ev['name']}({json.dumps(ev['input'])[:160]})") + "\n")
                elif t == "tool_result":
                    mark = "ok" if ev["ok"] else "error"
                    sys.stdout.write(c("2", f"  <- {ev['name']} {mark} {ev['elapsed_ms']}ms: {ev['preview'][:120].replace(chr(10), ' ')}") + "\n")
                elif t == "error":
                    sys.stdout.write("\n" + c("31", f"  ! {ev['message']}") + "\n")
                elif t == "done":
                    conversation_id = ev["conversation_id"]
                    if ev.get("usage"):
                        u = ev["usage"]
                        sys.stdout.write("\n" + c("2", f"  [{ev['iterations']} round(s), in {u.get('input_tokens', 0)} / out {u.get('output_tokens', 0)} tokens"
                                                      f"{', cache read ' + str(u['cache_read_input_tokens']) if u.get('cache_read_input_tokens') else ''}]") + "\n")
                    else:
                        sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finmcp-agent", description="Chat with your finances through the FinMCP MCP server")
    ap.add_argument("--server", choices=["inproc", "stdio", "http"], default="inproc", help="how to reach FinMCP (default: in-process)")
    ap.add_argument("--url", help="streamable HTTP URL when --server http")
    ap.add_argument("--token", default=os.environ.get("FINMCP_MCP_TOKEN"), help="personal MCP token (fm_...) that picks the account")
    ap.add_argument("--user-email", default=os.environ.get("FINMCP_USER_EMAIL"), help="serve this account (local mode)")
    ap.add_argument("--llm", choices=["auto", "openrouter", "anthropic", "rules"], default=None, help="server-side LLM mode")
    ap.add_argument("--driver", choices=["auto", "openrouter", "anthropic", "local"], default="auto", help="agent model driver")
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default=os.environ.get("FINMCP_AGENT_EFFORT", "medium"), choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--max-iterations", type=int, default=12)
    ap.add_argument("--seed-if-empty", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        return asyncio.run(chat(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
