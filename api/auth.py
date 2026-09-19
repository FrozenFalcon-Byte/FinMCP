"""Who is calling? Bearer tokens of three kinds, one `Principal` out.

- Supabase Auth access tokens (JWT): verified against the project's JWKS (ES256/RS256) or the legacy HS256 secret.
- Local session tokens (JWT): issued by this API when Supabase is not configured, signed with FINMCP_JWT_SECRET.
- Personal MCP tokens (`fm_...`): looked up by hash; what Claude Desktop, Claude Code and scripts present.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Any

import jwt
from jwt import PyJWKClient

from finmcp.config import Settings
from finmcp.db.accounts import AccountStore, Principal, Profile

log = logging.getLogger("finmcp.api.auth")

LOCAL_ISSUER = "finmcp-local"
LOCAL_TTL = 30 * 24 * 3600
AUDIENCE = "authenticated"


class RateLimiter:
    """Per-key sliding window; in memory, per process."""

    def __init__(self, limit: int = 8, window: int = 900):
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        hits = [t for t in self._hits[key] if now - t < self.window]
        self._hits[key] = hits
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.time())) >= self.limit

    def hit(self, key: str) -> None:
        with self._lock:
            self._prune(key, time.time()).append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


class Authenticator:
    def __init__(self, settings: Settings, store: AccountStore):
        self.settings = settings
        self.store = store
        self.mode = settings.auth_mode
        self._jwks: PyJWKClient | None = None
        if settings.supabase_configured and settings.supabase_url:
            self._jwks = PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ local sessions

    def issue_local_token(self, profile: Profile) -> str:
        now = int(time.time())
        claims = {"iss": LOCAL_ISSUER, "aud": AUDIENCE, "sub": profile.id, "email": profile.email,
                  "user_metadata": {"name": profile.name}, "iat": now, "exp": now + LOCAL_TTL}
        return jwt.encode(claims, self.settings.jwt_secret, algorithm="HS256")

    # ------------------------------------------------------------ verification

    def principal(self, token: str | None, *, client: str | None = None) -> Principal | None:
        if not token:
            return None
        token = token.strip()
        if token.startswith("fm_"):
            return self.store.resolve_token(token, client=client)
        claims = self.decode(token)
        if claims is None:
            return None
        user_id = str(claims.get("sub") or "")
        if not user_id:
            return None
        email = str(claims.get("email") or f"{user_id}@unknown.invalid")
        meta = claims.get("user_metadata") or {}
        name = str(meta.get("name") or meta.get("full_name") or claims.get("name") or email.split("@")[0])
        profile = self._ensure_profile(user_id, email, name)
        return Principal(user_id=profile.id, email=profile.email, name=profile.name, via=self.mode)

    def decode(self, token: str) -> dict[str, Any] | None:
        try:
            if self.mode == "local":
                return jwt.decode(token, self.settings.jwt_secret, algorithms=["HS256"], audience=AUDIENCE, issuer=LOCAL_ISSUER,
                                  options={"require": ["sub", "exp"]})
            header = jwt.get_unverified_header(token)
            alg = str(header.get("alg", ""))
            if alg == "HS256":
                if not self.settings.supabase_jwt_secret:
                    log.warning("HS256 Supabase token but SUPABASE_JWT_SECRET is not set")
                    return None
                key: Any = self.settings.supabase_jwt_secret
            elif alg in {"ES256", "RS256"} and self._jwks is not None:
                key = self._jwks.get_signing_key_from_jwt(token).key
            else:
                return None
            return jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE, options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as exc:
            log.debug("token rejected: %s", exc)
            return None

    def _ensure_profile(self, user_id: str, email: str, name: str) -> Profile:
        now = time.time()
        with self._lock:
            fresh = now - self._seen.get(user_id, 0) < 300
        if not fresh:
            profile = self.store.upsert_profile(user_id, email, name)
            with self._lock:
                self._seen[user_id] = now
            return profile
        profile = self.store.get_profile(user_id)
        return profile or self.store.upsert_profile(user_id, email, name)

    def forget(self, user_id: str) -> None:
        with self._lock:
            self._seen.pop(user_id, None)


def bearer_from_header(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, rest = value.partition(" ")
    if scheme.lower() != "bearer" or not rest.strip():
        return None
    return rest.strip()
