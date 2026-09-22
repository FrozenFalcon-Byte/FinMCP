"""Passkeys: the credential store, the challenge, and the session a passkey mints.

The ceremony itself is WebAuthn's, and testing it end to end would mean standing up a software authenticator to
produce real signatures. What is ours — that a challenge is single use and short-lived, that a credential round
trips, that the counter moves, and that the token a passkey issues is accepted in both identity modes — is here.
"""
import time

import pytest
from fastapi.testclient import TestClient

from api.auth import LOCAL_ISSUER, Authenticator
from api.routes.passkeys import _Challenges, _rp
from finmcp.db.accounts import AccountStore

from .conftest import make_settings, new_user

KEY = b"\x04" + bytes(range(64))   # not a real key; nothing here asks it to verify a signature


@pytest.fixture(scope="module")
def client():
    import uuid

    from api.main import create_app

    with TestClient(create_app()) as c:
        email = f"pk-{uuid.uuid4().hex[:6]}@example.com"
        r = c.post("/api/auth/register", json={"name": "Passkey User", "email": email, "password": "correct horse", "sample_data": False})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c


# ------------------------------------------------------------------ the store


def test_a_credential_round_trips(store: AccountStore):
    uid = new_user(store, "Keyholder")
    saved = store.add_passkey(uid, credential_id="abc123", public_key=KEY, sign_count=0, label="Mac · Safari")
    assert saved["label"] == "Mac · Safari" and saved["last_used_at"] is None

    found = store.find_passkey("abc123")
    assert found["user_id"] == uid and found["public_key"] == KEY and found["sign_count"] == 0
    assert store.passkey_ids(uid) == ["abc123"]

    store.touch_passkey(found["id"], 7)
    assert store.find_passkey("abc123")["sign_count"] == 7
    assert store.list_passkeys(uid)[0]["last_used_at"] is not None


def test_a_passkey_belongs_to_one_account(store: AccountStore):
    mine, theirs = new_user(store, "Mine"), new_user(store, "Theirs")
    saved = store.add_passkey(mine, credential_id="mine-1", public_key=KEY, sign_count=0)
    assert store.delete_passkey(theirs, saved["id"]) is False     # not yours to remove
    assert store.find_passkey("mine-1") is not None
    assert store.delete_passkey(mine, saved["id"]) is True
    assert store.find_passkey("mine-1") is None


# ------------------------------------------------------------------ the challenge


def test_a_challenge_is_spent_once():
    c = _Challenges()
    handle = c.issue(b"nonce-1", "user-a")
    assert c.spend(handle) == (b"nonce-1", "user-a")
    assert c.spend(handle) is None                                # replaying it gets nothing


def test_a_stale_challenge_is_gone():
    c = _Challenges()
    handle = c.issue(b"nonce-2")
    c._open[handle] = (time.time() - 1000, b"nonce-2", None)
    assert c.spend(handle) is None


def _fake(origin: str | None, public_url: str = "https://api.example.com"):
    from types import SimpleNamespace

    reg = SimpleNamespace(settings=SimpleNamespace(public_url=public_url))
    request = SimpleNamespace(headers={"origin": origin} if origin else {})
    return reg, request


def test_the_relying_party_is_the_page_not_the_api(monkeypatch):
    """The frontend is deployed apart from the API, so a passkey has to be bound to the site the person is on."""
    monkeypatch.setenv("FINMCP_CORS_ORIGINS", "https://fin-mcp.example.app")
    reg, request = _fake("https://fin-mcp.example.app")
    assert _rp(reg, request) == ("fin-mcp.example.app", ["https://fin-mcp.example.app"])


def test_an_origin_we_do_not_serve_is_not_trusted(monkeypatch):
    """The header is the browser's claim about the page. An unrecognised one is ignored, not believed."""
    monkeypatch.setenv("FINMCP_CORS_ORIGINS", "https://fin-mcp.example.app")
    reg, request = _fake("https://evil.example")
    assert _rp(reg, request) == ("api.example.com", ["https://api.example.com"])


def test_the_api_serving_the_app_itself_still_works(monkeypatch):
    monkeypatch.delenv("FINMCP_CORS_ORIGINS", raising=False)
    reg, request = _fake("https://api.example.com")
    assert _rp(reg, request) == ("api.example.com", ["https://api.example.com"])


def test_dev_runs_on_localhost(monkeypatch):
    monkeypatch.delenv("FINMCP_CORS_ORIGINS", raising=False)
    reg, request = _fake("http://localhost:5173", public_url="http://127.0.0.1:8000")
    assert _rp(reg, request) == ("localhost", ["http://localhost:5173"])

    # No browser in the call: an authenticator will not take an IP as an id, so the fallback names localhost.
    reg, request = _fake(None, public_url="http://127.0.0.1:8000")
    assert _rp(reg, request) == ("localhost", ["http://localhost:8000"])


def test_the_page_the_browser_names_is_never_rewritten(monkeypatch):
    """A page served from 127.0.0.1 gets 127.0.0.1. It will not work — an authenticator refuses an IP — but the
    refusal belongs to the browser, where it is legible, rather than to a quietly mismatched id from here."""
    monkeypatch.delenv("FINMCP_CORS_ORIGINS", raising=False)
    reg, request = _fake("http://127.0.0.1:8000", public_url="http://127.0.0.1:8000")
    assert _rp(reg, request) == ("127.0.0.1", ["http://127.0.0.1:8000"])


# ------------------------------------------------------------------ the session it mints


def test_a_passkey_token_is_accepted_even_in_supabase_mode(db, store: AccountStore):
    """A passkey is this API's proof, not Supabase's. The token it issues has to work in a deployment where
    Supabase owns the passwords, and must still be told apart from a Supabase token."""
    uid = new_user(store, "Dual Mode")
    profile = store.get_profile(uid)

    local = Authenticator(make_settings(), store)
    token = local.issue_local_token(profile)

    supa = Authenticator(make_settings(supabase_url="https://x.supabase.co", supabase_anon_key="anon", supabase_service_key="svc"), store)
    claims = supa.decode(token)
    assert claims is not None and claims["sub"] == uid and claims["iss"] == LOCAL_ISSUER

    forged = Authenticator(make_settings(jwt_secret="a-different-secret"), store).issue_local_token(profile)
    assert supa.decode(forged) is None                     # signed with the wrong key: still refused


# ------------------------------------------------------------------ the endpoints


def test_registration_options_are_offered_to_a_signed_in_account(client):
    r = client.post("/api/auth/passkeys/register/options")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handle"] and body["options"]["challenge"]
    assert body["options"]["rp"]["id"] and body["options"]["user"]["id"]


def test_a_made_up_answer_is_refused(client):
    r = client.post("/api/auth/passkeys/register/verify", json={"handle": "not-a-real-handle", "credential": {}})
    assert r.status_code == 400

    start = client.post("/api/auth/passkeys/register/options").json()
    r = client.post("/api/auth/passkeys/register/verify", json={"handle": start["handle"], "credential": {"id": "x", "response": {}}})
    assert r.status_code in (400, 422)


def test_sign_in_options_need_no_account(client):
    bare = TestClient(client.app)
    r = bare.post("/api/auth/passkeys/login/options")
    assert r.status_code == 200 and r.json()["options"]["challenge"]
    assert "allowCredentials" not in r.json()["options"] or not r.json()["options"]["allowCredentials"]


def test_an_unknown_credential_does_not_sign_anyone_in(client):
    bare = TestClient(client.app)
    start = bare.post("/api/auth/passkeys/login/options").json()
    r = bare.post("/api/auth/passkeys/login/verify", json={"handle": start["handle"], "credential": {"id": "nobody-has-this"}})
    assert r.status_code == 401


def test_the_list_is_empty_until_one_is_added(client):
    assert client.get("/api/auth/passkeys").json()["passkeys"] == []
    assert client.delete("/api/auth/passkeys/999999").status_code == 404


def test_config_advertises_passkeys(client):
    assert client.get("/api/auth/config").json()["passkeys"] is True
