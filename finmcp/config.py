"""Runtime settings, loaded from the environment and an optional .env file.

Two deployment shapes share one code path:
- Supabase: SUPABASE_URL + SUPABASE_ANON_KEY (auth) and SUPABASE_DB_URL (Postgres). Free tier is enough.
- Local: nothing configured. Accounts live in Postgres too (an embedded cluster under data/), passwords are
  checked by the API, and sessions are HS256 JWTs signed with a secret generated into data/.jwt-secret.
"""
from __future__ import annotations

import contextlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    supabase_url: str | None
    supabase_anon_key: str | None
    supabase_service_key: str | None
    supabase_jwt_secret: str | None
    oauth_providers: tuple[str, ...]
    jwt_secret: str
    public_url: str
    model: str
    currency: str
    llm_mode: str  # auto | anthropic | rules
    api_key_present: bool
    fallbacks: bool
    seed_if_empty: bool
    pg_port: int
    data_dir: Path

    @property
    def use_llm(self) -> bool:
        if self.llm_mode == "rules":
            return False
        if self.llm_mode == "anthropic":
            return True
        return self.api_key_present

    @property
    def auth_mode(self) -> str:
        return "supabase" if self.supabase_url and self.supabase_anon_key else "local"

    @property
    def supabase_configured(self) -> bool:
        return self.auth_mode == "supabase"


def _local_jwt_secret(data_dir: Path, value: str | None) -> str:
    if value:
        return value
    path = data_dir / ".jwt-secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret, encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return secret


def load_settings(**overrides: object) -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    env = os.environ
    llm_mode = str(overrides.get("llm_mode") or env.get("FINMCP_LLM", "auto")).lower()
    if llm_mode not in {"auto", "anthropic", "rules"}:
        llm_mode = "auto"
    key_present = bool(env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"))
    data_dir = Path(str(overrides.get("data_dir") or env.get("FINMCP_DATA_DIR") or DATA_DIR))
    supabase_url = (str(overrides.get("supabase_url") or env.get("SUPABASE_URL") or "")).strip().rstrip("/") or None
    providers = tuple(p.strip().lower() for p in str(env.get("SUPABASE_OAUTH_PROVIDERS", "")).split(",") if p.strip())
    return Settings(
        database_url=str(overrides.get("database_url") or env.get("FINMCP_DATABASE_URL") or env.get("SUPABASE_DB_URL") or "") or None,
        supabase_url=supabase_url,
        supabase_anon_key=(env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_PUBLISHABLE_KEY") or "").strip() or None,
        supabase_service_key=(env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SECRET_KEY") or "").strip() or None,
        supabase_jwt_secret=(env.get("SUPABASE_JWT_SECRET") or "").strip() or None,
        oauth_providers=providers,
        jwt_secret=_local_jwt_secret(data_dir, str(overrides.get("jwt_secret") or env.get("FINMCP_JWT_SECRET") or "") or None),
        public_url=str(overrides.get("public_url") or env.get("FINMCP_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/"),
        model=str(overrides.get("model") or env.get("FINMCP_MODEL") or "claude-opus-5"),
        currency=str(overrides.get("currency") or env.get("FINMCP_CURRENCY") or "INR"),
        llm_mode=llm_mode,
        api_key_present=key_present,
        fallbacks=_truthy(str(overrides.get("fallbacks", env.get("FINMCP_FALLBACKS", "1"))), True),
        seed_if_empty=bool(overrides.get("seed_if_empty", _truthy(env.get("FINMCP_SEED_IF_EMPTY")))),
        pg_port=int(str(overrides.get("pg_port") or env.get("FINMCP_PG_PORT") or "54329")),
        data_dir=data_dir,
    )
