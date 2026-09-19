"""Test fixtures. One embedded PostgreSQL cluster per session; every test gets its own account, so Row Level
Security (not a fresh database) is what keeps tests apart. That is also how production isolates people."""
from __future__ import annotations

import dataclasses
import os
import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest
from mcp import Client

from finmcp.config import ROOT, Settings, load_settings
from finmcp.db import Database, open_database
from finmcp.db.accounts import AccountStore
from finmcp.db.devpg import temp_cluster
from finmcp.db.repository import Repository
from finmcp.db.seed import seed_demo_data
from finmcp.server import create_server, seed_account
from finmcp.taxonomy import seed_categories

TODAY = date(2026, 9, 17)

_TMP = Path(tempfile.mkdtemp(prefix="finmcp-tests-"))
_CLUSTER = temp_cluster(ROOT, _TMP)
_CLUSTER.start()
os.environ.update({
    "FINMCP_DATABASE_URL": _CLUSTER.url,
    "FINMCP_DATA_DIR": str(_TMP / "data"),
    "FINMCP_JWT_SECRET": "test-secret-not-for-production-0123456789abcdef",
    "FINMCP_LLM": "rules",
    "FINMCP_AGENT_DRIVER": "local",
    "FINMCP_PUBLIC_URL": "http://testserver",
})
# Blank (not unset) so the developer's real .env, which load_dotenv never lets override the environment, stays out
# of tests and of the stdio servers they spawn.
for var in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_DB_URL", "SUPABASE_JWT_SECRET", "SUPABASE_SERVICE_ROLE_KEY", "ANTHROPIC_API_KEY"):
    os.environ[var] = ""
_DB = open_database(_CLUSTER.url)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    _DB.close()
    _CLUSTER.destroy()


def make_settings(**overrides) -> Settings:
    base = dataclasses.replace(load_settings(), llm_mode="rules", api_key_present=False, fallbacks=False, seed_if_empty=False, currency="INR")
    return dataclasses.replace(base, **overrides)


@pytest.fixture(scope="session")
def db() -> Database:
    return _DB


@pytest.fixture(scope="session")
def store(db: Database) -> AccountStore:
    return AccountStore(db)


def new_user(store: AccountStore, name: str = "Test User") -> str:
    uid = str(uuid.uuid4())
    store.upsert_profile(uid, f"{uid[:8]}@example.com", name)
    return uid


@pytest.fixture
def user_id(store: AccountStore) -> str:
    return new_user(store)


@pytest.fixture
def repo(db: Database, user_id: str) -> Repository:
    r = Repository(db, user_id, client="test")
    seed_categories(r)
    return r


@pytest.fixture
def seeded_repo(repo: Repository) -> Repository:
    seed_demo_data(repo, days=90, end=TODAY)
    return repo


def make_server(db: Database, store: AccountStore, *, seed: bool = True, client: str = "test"):
    uid = new_user(store)
    server = create_server(make_settings(), db=db, user_id=uid, client=client)
    if seed:
        seed_demo_data(server.finmcp.tenant().repo, days=90, end=TODAY)
    return server


@pytest.fixture
def server(db: Database, store: AccountStore):
    return make_server(db, store)


def connect(server) -> Client:
    """In-process MCP client. Use as `async with connect(server) as client:` inside the test body
    (an async-generator fixture would close anyio's cancel scope from another task)."""
    return Client(server)


def tool_names(listing) -> list[str]:
    items = getattr(listing, "tools", listing)
    return [t.name for t in items]


def result_data(result):
    """Structured content if present, else parsed text."""
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        return sc
    import json

    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


def result_text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


__all__ = ["TODAY", "connect", "make_server", "make_settings", "new_user", "result_data", "result_text", "seed_account", "tool_names"]
