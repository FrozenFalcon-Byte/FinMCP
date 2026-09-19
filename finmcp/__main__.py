"""Command line entry point: `python -m finmcp` (stdio, for MCP hosts that launch a process) or `--transport http`.

The process serves ONE account. Pick it with --token (a personal token created under Connect in the app; also read
from FINMCP_MCP_TOKEN) or --user-email. With neither, local mode falls back to a demo account so the server can be
tried without the web app."""
from __future__ import annotations

import argparse
import logging
import os
import sys

import anyio

from .config import Settings, load_settings
from .db import Database, database_for
from .db.accounts import AccountStore, Principal
from .server import create_server, seed_account

DEMO_EMAIL = "demo@finmcp.local"
DEMO_ID = "00000000-0000-4000-8000-00000000f1a1"


def resolve_principal(settings: Settings, db: Database, *, token: str | None, email: str | None, allow_demo: bool = True) -> Principal:
    store = AccountStore(db)
    token = token or os.environ.get("FINMCP_MCP_TOKEN")
    if token:
        principal = store.resolve_token(token, client="stdio")
        if principal is None:
            raise SystemExit("That MCP token is not valid. Create one under Connect in the web app.")
        return principal
    email = email or os.environ.get("FINMCP_USER_EMAIL")
    if email:
        profile = store.get_profile_by_email(email)
        if profile is None:
            raise SystemExit(f"No account with email {email!r} has signed in yet.")
        return Principal(user_id=profile.id, email=profile.email, name=profile.name, via="local")
    if settings.supabase_configured or not allow_demo:
        raise SystemExit("Pass --token fm_... (create one under Connect in the web app) or --user-email.")
    profile = store.upsert_profile(DEMO_ID, DEMO_EMAIL, "Demo")
    return Principal(user_id=profile.id, email=profile.email, name=profile.name, via="local")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="finmcp", description="FinMCP personal-finance MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="stdio (default) or streamable HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--token", help="Personal MCP token (fm_...) that picks the account; also FINMCP_MCP_TOKEN")
    parser.add_argument("--user-email", help="Serve the account with this email (local mode)")
    parser.add_argument("--client", default="stdio", help="Client label recorded on writes (default: stdio)")
    parser.add_argument("--llm", choices=["auto", "openrouter", "anthropic", "rules"], help="LLM mode (default: FINMCP_LLM or auto)")
    parser.add_argument("--seed", action="store_true", help="Insert demo data (idempotent) before serving")
    parser.add_argument("--seed-only", action="store_true", help="Insert demo data and exit")
    parser.add_argument("--seed-if-empty", action="store_true", help="Insert demo data only when the ledger is empty")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    # stdio transport owns stdout; every log line must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("finmcp")

    settings = load_settings(llm_mode=args.llm, seed_if_empty=args.seed_if_empty or args.seed or args.seed_only)
    db = database_for(settings)
    principal = resolve_principal(settings, db, token=args.token, email=args.user_email)
    server = create_server(settings, db=db, user_id=principal.user_id, client=args.client)
    if args.seed or args.seed_only:
        log.info("Seed: %s", seed_account(server, only_if_empty=False))
    elif args.seed_if_empty:
        seed_account(server, only_if_empty=True)
    st = server.finmcp.tenant()  # type: ignore[attr-defined]
    log.info("FinMCP ready: account=%s (%s) transactions=%d provider=%s rls=%s", principal.email, principal.via,
             st.repo.count_transactions(), st.provider.name, db.rls)
    if args.seed_only:
        return 0
    async def serve() -> None:
        # Resource subscriptions start their own change pump when a client opens `subscriptions/listen`.
        if args.transport == "stdio":
            await server.run_stdio_async()
        else:
            log.info("Serving streamable HTTP on http://%s:%d/mcp", args.host, args.port)
            await server.run_streamable_http_async(host=args.host, port=args.port)

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
