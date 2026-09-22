"""Accounts, profiles and personal MCP tokens. Runs as the connecting role (not tenant-scoped) because these
lookups happen before we know who is calling.

- Supabase mode: identities come from Supabase Auth; `profiles` mirrors id/email/name on first sight.
- Local mode: `local_users` holds scrypt password hashes and the API signs its own JWTs.
- Both modes: `mcp_tokens` are long-lived bearer tokens that MCP clients present (`fm_...`)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from .database import Database
from .repository import clean_row

TOKEN_PREFIX = "fm_"
MIN_PASSWORD = 8
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ passwords


def hash_password(password: str, *, n: int = 2**14, r: int = 8, p: int = 1) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return "scrypt$" + "$".join([str(n), str(r), str(p), base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = encoded.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL.match(email)) and len(email) <= 254


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ models


@dataclass(frozen=True)
class Profile:
    id: str
    email: str
    name: str
    currency: str
    created_at: str
    last_seen_at: str | None = None
    avatar: str | None = None
    monthly_income: float | None = None
    pay_day: int | None = None
    keep_pct: int | None = None
    onboarded_at: str | None = None
    tour_seen_at: str | None = None

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "name": self.name, "currency": self.currency, "created_at": self.created_at,
                "avatar": self.avatar, "monthly_income": float(self.monthly_income) if self.monthly_income is not None else None,
                "pay_day": self.pay_day, "keep_pct": self.keep_pct,
                "onboarded_at": self.onboarded_at, "tour_seen_at": self.tour_seen_at}


@dataclass(frozen=True)
class Principal:
    """Who is calling, however they authenticated."""

    user_id: str
    email: str
    name: str
    via: str  # "supabase" | "local" | "token"
    token_id: str | None = None
    token_name: str | None = None


# ------------------------------------------------------------------ store


class AccountStore:
    def __init__(self, db: Database):
        self.db = db

    # ---- profiles

    def upsert_profile(self, user_id: str, email: str, name: str | None = None) -> Profile:
        with self.db.admin() as conn:
            row = conn.execute(
                """INSERT INTO profiles (id, email, name, last_seen_at) VALUES (%s, %s, %s, now())
                   ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email,
                     name = CASE WHEN profiles.name = '' THEN EXCLUDED.name ELSE profiles.name END,
                     last_seen_at = now()
                   RETURNING id, email, name, currency, created_at, last_seen_at, avatar, monthly_income, pay_day, keep_pct, onboarded_at, tour_seen_at""",
                (user_id, normalize_email(email), (name or "").strip()),
            ).fetchone()
        return Profile(**{k: str(v) if k == "id" else v for k, v in clean_row(row).items()})  # type: ignore[arg-type]

    def get_profile(self, user_id: str) -> Profile | None:
        with self.db.admin() as conn:
            row = conn.execute("SELECT id, email, name, currency, created_at, last_seen_at, avatar, monthly_income, pay_day, keep_pct, onboarded_at, tour_seen_at FROM profiles WHERE id = %s", (user_id,)).fetchone()
        return Profile(**{k: str(v) if k == "id" else v for k, v in clean_row(row).items()}) if row else None  # type: ignore[arg-type]

    def get_profile_by_email(self, email: str) -> Profile | None:
        with self.db.admin() as conn:
            row = conn.execute("SELECT id, email, name, currency, created_at, last_seen_at, avatar, monthly_income, pay_day, keep_pct, onboarded_at, tour_seen_at FROM profiles WHERE email = %s", (normalize_email(email),)).fetchone()
        return Profile(**{k: str(v) if k == "id" else v for k, v in clean_row(row).items()}) if row else None  # type: ignore[arg-type]

    MAX_AVATAR = 400_000  # characters of data URL; the browser sends a 256px square, which is a fraction of this

    def update_profile(self, user_id: str, *, name: str | None = None, currency: str | None = None,
                       avatar: str | None = None, monthly_income: float | None = None, pay_day: int | None = None,
                       keep_pct: int | None = None, onboarded: bool = False, tour_seen: bool = False) -> Profile:
        """Change what the person told us about themselves. Every field is optional; only what is passed is written.

        The avatar is a small square data URL kept in the row rather than on disk, because the container's disk does
        not survive a deploy and a face vanishing after a restart is worse than a few kilobytes in the table."""
        sets: list[str] = []
        params: list[Any] = []
        if avatar is not None:
            avatar = avatar.strip()
            if avatar and not avatar.startswith("data:image/"):
                raise ValueError("A photo must be an image.")
            if len(avatar) > self.MAX_AVATAR:
                raise ValueError("That photo is too large — 400KB or less, please.")
            sets.append("avatar = %s")
            params.append(avatar or None)
        if monthly_income is not None:
            if not 0 <= float(monthly_income) <= 1e11:
                raise ValueError("Monthly income looks wrong.")
            sets.append("monthly_income = %s")
            params.append(float(monthly_income))
        if pay_day is not None:
            if not 1 <= int(pay_day) <= 31:
                raise ValueError("Pay day is a day of the month, 1 to 31.")
            sets.append("pay_day = %s")
            params.append(int(pay_day))
        if keep_pct is not None:
            if not 0 <= int(keep_pct) <= 90:
                raise ValueError("Keep between 0 and 90 percent.")
            sets.append("keep_pct = %s")
            params.append(int(keep_pct))
        if onboarded:
            sets.append("onboarded_at = coalesce(onboarded_at, now())")
        if tour_seen:
            sets.append("tour_seen_at = now()")
        if name is not None:
            name = " ".join(name.split())
            if not 1 <= len(name) <= 80:
                raise ValueError("Name must be between 1 and 80 characters.")
            sets.append("name = %s")
            params.append(name)
        if currency is not None:
            currency = currency.strip().upper()
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError("Currency must be a 3-letter code like INR or USD.")
            sets.append("currency = %s")
            params.append(currency)
        if sets:
            with self.db.admin() as conn:
                conn.execute(f"UPDATE profiles SET {', '.join(sets)} WHERE id = %s", (*params, user_id))
        profile = self.get_profile(user_id)
        if profile is None:
            raise ValueError("Profile not found")
        return profile

    def count_profiles(self) -> int:
        with self.db.admin() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"])  # type: ignore[index]

    def delete_profile(self, user_id: str) -> bool:
        with self.db.admin() as conn:
            n = conn.execute("DELETE FROM profiles WHERE id = %s", (user_id,)).rowcount
            conn.execute("DELETE FROM local_users WHERE id = %s", (user_id,))
        return n > 0

    # ---- local accounts (no Supabase)

    def create_local_user(self, *, email: str, name: str, password: str) -> Profile:
        email = normalize_email(email)
        name = " ".join(name.split())
        if not valid_email(email):
            raise ValueError("That does not look like an email address.")
        if not 1 <= len(name) <= 80:
            raise ValueError("Name must be between 1 and 80 characters.")
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
        user_id = str(uuid.uuid4())
        with self.db.admin() as conn:
            exists = conn.execute("SELECT 1 FROM local_users WHERE email = %s", (email,)).fetchone()
            if exists:
                raise ValueError("An account with that email already exists.")
            conn.execute("INSERT INTO local_users (id, email, name, password_hash) VALUES (%s, %s, %s, %s)",
                         (user_id, email, name, hash_password(password)))
        return self.upsert_profile(user_id, email, name)

    def authenticate_local(self, email: str, password: str) -> Profile | None:
        with self.db.admin() as conn:
            row = conn.execute("SELECT id, email, name, password_hash FROM local_users WHERE email = %s", (normalize_email(email),)).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return self.upsert_profile(str(row["id"]), row["email"], row["name"])

    def local_password_state(self, *, email: str | None = None, user_id: str | None = None) -> tuple[str, str] | None:
        """(user id, password hash) for a local account, looked up by email or id."""
        with self.db.admin() as conn:
            if user_id is not None:
                row = conn.execute("SELECT id, password_hash FROM local_users WHERE id = %s", (user_id,)).fetchone()
            else:
                row = conn.execute("SELECT id, password_hash FROM local_users WHERE email = %s", (normalize_email(email or ""),)).fetchone()
        return (str(row["id"]), row["password_hash"]) if row else None

    def set_local_password(self, user_id: str, password: str) -> Profile:
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
        with self.db.admin() as conn:
            row = conn.execute("UPDATE local_users SET password_hash = %s WHERE id = %s RETURNING email, name",
                               (hash_password(password), user_id)).fetchone()
        if row is None:
            raise ValueError("That account no longer exists.")
        return self.upsert_profile(user_id, row["email"], row["name"])

    def count_local_users(self) -> int:
        with self.db.admin() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM local_users").fetchone()["n"])  # type: ignore[index]

    # ---- personal MCP tokens

    def create_token(self, user_id: str, name: str) -> tuple[str, dict[str, Any]]:
        """Returns (plaintext token, record). The plaintext is shown once and never stored."""
        name = " ".join(name.split())[:60] or "MCP client"
        token = TOKEN_PREFIX + secrets.token_hex(24)
        prefix = token[:11]
        with self.db.admin() as conn:
            row = conn.execute(
                """INSERT INTO mcp_tokens (user_id, name, prefix, token_hash) VALUES (%s, %s, %s, %s)
                   RETURNING id, name, prefix, created_at, last_used_at, last_client""",
                (user_id, name, prefix, hash_token(token)),
            ).fetchone()
        rec = clean_row(row) or {}
        rec["id"] = str(rec["id"])
        return token, rec

    def list_tokens(self, user_id: str) -> list[dict[str, Any]]:
        with self.db.admin() as conn:
            rows = conn.execute("SELECT id, name, prefix, created_at, last_used_at, last_client FROM mcp_tokens WHERE user_id = %s ORDER BY created_at DESC",
                                (user_id,)).fetchall()
        out = []
        for r in rows:
            rec = clean_row(r) or {}
            rec["id"] = str(rec["id"])
            out.append(rec)
        return out

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        with self.db.admin() as conn:
            return conn.execute("DELETE FROM mcp_tokens WHERE user_id = %s AND id = %s", (user_id, token_id)).rowcount > 0

    def resolve_token(self, token: str, *, client: str | None = None) -> Principal | None:
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        with self.db.admin() as conn:
            row = conn.execute(
                """SELECT t.id AS token_id, t.name AS token_name, p.id, p.email, p.name
                   FROM mcp_tokens t JOIN profiles p ON p.id = t.user_id WHERE t.token_hash = %s""",
                (hash_token(token),),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE mcp_tokens SET last_used_at = now(), last_client = COALESCE(%s, last_client) WHERE id = %s",
                         (client, row["token_id"]))
        return Principal(user_id=str(row["id"]), email=row["email"], name=row["name"], via="token",
                         token_id=str(row["token_id"]), token_name=row["token_name"])
