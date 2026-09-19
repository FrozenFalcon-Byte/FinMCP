"""Accounts, tokens, JWT verification and per-account isolation through the API."""
from __future__ import annotations

import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from api.auth import Authenticator
from finmcp.db.accounts import AccountStore, hash_password, verify_password
from tests.conftest import make_settings


def test_password_hashing_roundtrip():
    h = hash_password("hunter2 hunter2")
    assert h.startswith("scrypt$") and verify_password("hunter2 hunter2", h)
    assert not verify_password("hunter2 hunter3", h)
    assert not verify_password("anything", "garbage")
    assert hash_password("same") != hash_password("same")  # salted


def test_local_accounts_and_tokens(store: AccountStore):
    tag = uuid.uuid4().hex[:6]
    with pytest.raises(ValueError):
        store.create_local_user(email="nope", name="x", password="longenough")
    with pytest.raises(ValueError):
        store.create_local_user(email=f"a{tag}@b.co", name="x", password="short")
    u = store.create_local_user(email=f"A{tag}@B.co", name="  Ada   Lovelace ", password="longenough")
    assert u.email == f"a{tag}@b.co" and u.name == "Ada Lovelace" and u.currency == "INR"
    with pytest.raises(ValueError):
        store.create_local_user(email=f"a{tag}@b.co", name="dup", password="longenough")
    assert store.authenticate_local(f"a{tag}@b.co", "wrong") is None and store.authenticate_local("ghost@b.co", "longenough") is None
    assert store.authenticate_local(f"a{tag}@b.co", "longenough").id == u.id
    token, rec = store.create_token(u.id, "Claude Desktop")
    assert token.startswith("fm_") and rec["prefix"] == token[:11] and rec["name"] == "Claude Desktop"
    p = store.resolve_token(token, client="pytest")
    assert p is not None and p.user_id == u.id and p.via == "token" and p.token_name == "Claude Desktop"
    assert store.list_tokens(u.id)[0]["last_client"] == "pytest"
    assert store.resolve_token("fm_bogus") is None and store.resolve_token("") is None
    assert store.revoke_token(u.id, rec["id"]) and store.resolve_token(token) is None
    assert store.update_profile(u.id, currency="usd").currency == "USD"
    with pytest.raises(ValueError):
        store.update_profile(u.id, currency="rupees")


def test_local_jwt_roundtrip(store: AccountStore):
    auth = Authenticator(make_settings(), store)
    u = store.upsert_profile(str(uuid.uuid4()), "jwt@example.com", "Jay")
    tok = auth.issue_local_token(u)
    p = auth.principal(tok)
    assert p is not None and p.user_id == u.id and p.email == "jwt@example.com" and p.via == "local"
    assert auth.principal("garbage") is None and auth.principal(None) is None
    expired = jwt.encode({"iss": "finmcp-local", "aud": "authenticated", "sub": u.id, "exp": int(time.time()) - 10}, auth.settings.jwt_secret, algorithm="HS256")
    assert auth.principal(expired) is None
    other_issuer = jwt.encode({"iss": "someone-else", "aud": "authenticated", "sub": u.id, "exp": int(time.time()) + 100}, auth.settings.jwt_secret, algorithm="HS256")
    assert auth.principal(other_issuer) is None


def test_supabase_hs256_token(store: AccountStore):
    settings = make_settings(supabase_url="https://demo.supabase.co", supabase_anon_key="anon", supabase_jwt_secret="super-secret-legacy-jwt-secret-of-forty-chars!!")
    auth = Authenticator(settings, store)
    assert auth.mode == "supabase"
    uid = str(uuid.uuid4())
    claims = {"iss": "https://demo.supabase.co/auth/v1", "aud": "authenticated", "sub": uid, "email": "sb@example.com",
              "user_metadata": {"name": "Sabrina"}, "role": "authenticated", "exp": int(time.time()) + 3600}
    p = auth.principal(jwt.encode(claims, "super-secret-legacy-jwt-secret-of-forty-chars!!", algorithm="HS256"))
    assert p is not None and p.user_id == uid and p.name == "Sabrina" and p.via == "supabase"
    assert store.get_profile(uid).email == "sb@example.com"  # mirrored on first sight
    assert auth.principal(jwt.encode(claims, "wrong-secret-legacy-jwt-secret-of-forty-chars!", algorithm="HS256")) is None
    assert auth.principal(jwt.encode({**claims, "aud": "anon"}, "super-secret-legacy-jwt-secret-of-forty-chars!!", algorithm="HS256")) is None


def test_supabase_es256_token_via_jwks(store: AccountStore):
    from cryptography.hazmat.primitives.asymmetric import ec

    settings = make_settings(supabase_url="https://demo.supabase.co", supabase_anon_key="anon")
    auth = Authenticator(settings, store)
    key = ec.generate_private_key(ec.SECP256R1())

    class FakeJWKS:
        def get_signing_key_from_jwt(self, token):  # noqa: ARG002
            return type("K", (), {"key": key.public_key()})()

    auth._jwks = FakeJWKS()
    uid = str(uuid.uuid4())
    token = jwt.encode({"aud": "authenticated", "sub": uid, "email": "es@example.com", "exp": int(time.time()) + 60}, key, algorithm="ES256", headers={"kid": "k1"})
    p = auth.principal(token)
    assert p is not None and p.user_id == uid and p.email == "es@example.com"
    # HS256 tokens are refused when no legacy secret is configured
    assert auth.principal(jwt.encode({"aud": "authenticated", "sub": uid, "exp": int(time.time()) + 60}, "x" * 40, algorithm="HS256")) is None


# ------------------------------------------------------------------ through the API


@pytest.fixture(scope="module")
def app_client():
    from api.main import create_app

    with TestClient(create_app()) as c:
        yield c


def register(c: TestClient, name: str, email: str, sample_data: bool = False) -> dict:
    r = c.post("/api/auth/register", json={"name": name, "email": email, "password": "plain words ledger", "sample_data": sample_data})
    assert r.status_code == 201, r.text
    return r.json()


def test_auth_config_is_public(app_client: TestClient):
    r = app_client.get("/api/auth/config")
    assert r.status_code == 200 and r.json()["mode"] == "local" and r.json()["mcp_endpoint"].endswith("/mcp")


def test_register_me_login_flow(app_client: TestClient):
    c = app_client
    tag = uuid.uuid4().hex[:6]
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/transactions").status_code == 401
    s = register(c, "Ada", f"ada-{tag}@example.com")
    assert s["token_type"] == "bearer" and s["user"]["email"] == f"ada-{tag}@example.com" and s["sample_data"] is False
    h = {"Authorization": f"Bearer {s['access_token']}"}
    me = c.get("/api/auth/me", headers=h)
    assert me.status_code == 200 and me.json()["user"]["name"] == "Ada" and me.json()["via"] == "local"
    assert c.post("/api/auth/register", json={"name": "Dup", "email": f"ada-{tag}@example.com", "password": "plain words ledger"}).status_code == 400
    assert c.post("/api/auth/register", json={"name": "Short", "email": f"s-{tag}@example.com", "password": "short"}).status_code == 422
    assert c.post("/api/auth/login", json={"email": f"ada-{tag}@example.com", "password": "wrong password"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": f"ADA-{tag}@example.com", "password": "plain words ledger"})
    assert r.status_code == 200 and r.json()["user"]["id"] == s["user"]["id"]
    assert c.get("/api/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    # profile changes
    r = c.patch("/api/auth/profile", json={"name": "Ada L.", "currency": "usd"}, headers=h)
    assert r.status_code == 200 and r.json()["user"]["currency"] == "USD"
    assert c.get("/api/health", headers=h).json()["status"]["currency"] == "USD"


def test_accounts_are_isolated(app_client: TestClient):
    c = app_client
    tag = uuid.uuid4().hex[:6]
    ada = register(c, "Ada", f"ada2-{tag}@example.com")
    grace = register(c, "Grace", f"grace-{tag}@example.com")
    ha = {"Authorization": f"Bearer {ada['access_token']}"}
    hg = {"Authorization": f"Bearer {grace['access_token']}"}
    r = c.post("/api/transactions", json={"date": "2026-09-10", "amount": 120, "merchant": "Ada Only Cafe"}, headers=ha)
    assert r.status_code == 201 and r.json()["transaction"]["client"] == "web"
    assert c.get("/api/transactions", headers=ha).json()["total"] == 1
    assert c.get("/api/transactions", headers=hg).json()["total"] == 0
    assert c.get("/api/transactions", params={"search": "Ada Only"}, headers=hg).json()["total"] == 0
    assert c.get("/api/chats", headers=hg).json() == []
    tx_id = r.json()["transaction"]["id"]
    assert c.delete(f"/api/transactions/{tx_id}", headers=hg).status_code == 400  # not found for Grace
    assert c.get("/api/activity", headers=hg).json()["items"] == []


def test_mcp_tokens_via_api(app_client: TestClient):
    c = app_client
    tag = uuid.uuid4().hex[:6]
    s = register(c, "Tok", f"tok-{tag}@example.com")
    h = {"Authorization": f"Bearer {s['access_token']}"}
    r = c.post("/api/mcp/tokens", json={"name": "Claude Desktop"}, headers=h)
    assert r.status_code == 201 and r.json()["token"].startswith("fm_") and r.json()["endpoint"].endswith("/mcp")
    tok = r.json()["token"]
    # a personal token works on the API too
    ht = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/auth/me", headers=ht).json()["via"] == "token"
    assert c.get("/api/mcp/tokens", headers=h).json()[0]["name"] == "Claude Desktop"
    cat = c.get("/api/mcp/catalog", headers=h).json()
    assert len(cat["tools"]) >= 20 and any(t["name"] == "get_overview" for t in cat["tools"]) and len(cat["prompts"]) >= 4
    assert c.delete(f"/api/mcp/tokens/{r.json()['record']['id']}", headers=h).json()["revoked"]
    assert c.get("/api/auth/me", headers=ht).status_code == 401


def test_login_rate_limit(app_client: TestClient):
    c = app_client
    tag = uuid.uuid4().hex[:6]
    register(c, "Limit", f"limit-{tag}@example.com")
    for _ in range(8):
        assert c.post("/api/auth/login", json={"email": f"limit-{tag}@example.com", "password": "wrong password"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": f"limit-{tag}@example.com", "password": "plain words ledger"}).status_code == 429


def test_delete_account(app_client: TestClient):
    c = app_client
    tag = uuid.uuid4().hex[:6]
    s = register(c, "Gone", f"gone-{tag}@example.com", sample_data=True)
    h = {"Authorization": f"Bearer {s['access_token']}"}
    assert c.get("/api/transactions", headers=h).json()["total"] > 100
    r = c.delete("/api/auth/account", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] and r.json()["rows"]["transactions"] > 100
    assert c.post("/api/auth/login", json={"email": f"gone-{tag}@example.com", "password": "plain words ledger"}).status_code == 401


def test_password_reset_flow(app_client: TestClient, caplog):
    import logging
    import re

    c = app_client
    email = f"reset-{uuid.uuid4().hex[:6]}@example.com"
    register(c, "Reset", email)
    with caplog.at_level(logging.WARNING, logger="finmcp.api.auth"):
        r = c.post("/api/auth/password/forgot", json={"email": email})
        assert r.json() == {"sent": True} and "token" not in r.text
        assert c.post("/api/auth/password/forgot", json={"email": "nobody@example.com"}).json() == {"sent": True}
    token = re.search(r"reset-password\?token=(\S+)", caplog.text).group(1)
    assert c.post("/api/auth/password/reset", json={"token": token, "password": "short"}).status_code == 400
    r = c.post("/api/auth/password/reset", json={"token": token, "password": "a brand new passphrase"})
    assert r.status_code == 200 and r.json()["user"]["email"] == email and r.json()["access_token"]
    assert c.post("/api/auth/password/reset", json={"token": token, "password": "another new passphrase"}).status_code == 400  # single use
    assert c.post("/api/auth/login", json={"email": email, "password": "plain words ledger"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": email, "password": "a brand new passphrase"}).status_code == 200
    assert c.post("/api/auth/password/reset", json={"token": "x" * 40, "password": "a brand new passphrase"}).status_code == 400
