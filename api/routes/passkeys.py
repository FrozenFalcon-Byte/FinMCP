"""Passkeys: signing in with the device's screen lock.

A passkey is a key pair the browser's authenticator makes for this site. The private half stays on the device
behind Face ID, a fingerprint or the laptop's PIN, and never travels; we keep the public half and a counter. There
is nothing here to phish, reuse or leak, which is the whole point of offering it beside the password.

Both identity modes are served. Supabase issues the session when you sign in with a password, but a passkey is
this API's own proof — so a passkey sign-in mints this API's own session token, and `Authenticator.decode` accepts
those alongside Supabase's. The passkey is bound to a profile id, which is the same id either way.

Challenges live in this process for two minutes. One instance serves a sign-in from start to finish, and a
challenge that outlives its ceremony is a replay waiting to happen.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlparse

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from finmcp.db.accounts import Principal, Profile

from ..auth import LOCAL_TTL, RateLimiter
from ..deps import Registry, get_registry, require_principal

log = logging.getLogger("finmcp.api.passkeys")
router = APIRouter(tags=["auth"])

CHALLENGE_TTL = 120
RP_NAME = "FinMCP"
_limiter = RateLimiter(limit=20, window=900)


class _Challenges:
    """Handed out with the options, spent on the answer. Single use, and short-lived."""

    def __init__(self) -> None:
        self._open: dict[str, tuple[float, bytes, str | None]] = {}

    def issue(self, challenge: bytes, user_id: str | None = None) -> str:
        self._sweep()
        handle = secrets.token_urlsafe(18)
        self._open[handle] = (time.time(), challenge, user_id)
        return handle

    def spend(self, handle: str) -> tuple[bytes, str | None] | None:
        self._sweep()
        hit = self._open.pop(handle, None)
        return (hit[1], hit[2]) if hit else None

    def _sweep(self) -> None:
        cut = time.time() - CHALLENGE_TTL
        for k in [k for k, v in self._open.items() if v[0] < cut]:
            self._open.pop(k, None)


_challenges = _Challenges()


def _rp(reg: Registry) -> tuple[str, list[str]]:
    """(relying party id, acceptable origins). The id is the site's registrable domain: a passkey made on
    fin-mcp.vercel.app has to be presented there and nowhere else, which is what makes it unphishable."""
    url = urlparse(reg.settings.public_url)
    host = url.hostname or "localhost"
    origins = [f"{url.scheme}://{url.netloc}"]
    if host in {"localhost", "127.0.0.1"}:
        host = "localhost"
        origins = ["http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:5173", "http://127.0.0.1:8000", *origins]
    return host, origins


def _session(reg: Registry, profile: Profile) -> dict[str, Any]:
    return {"access_token": reg.auth.issue_local_token(profile), "token_type": "bearer", "expires_in": LOCAL_TTL, "user": profile.public()}


class Answer(BaseModel):
    handle: str = Field(min_length=8, max_length=64)
    credential: dict[str, Any]
    label: str | None = Field(default=None, max_length=60)


# ------------------------------------------------------------------ enrolling, from inside the app


@router.get("/auth/passkeys")
async def list_passkeys(principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    keys = await anyio.to_thread.run_sync(lambda: reg.store.list_passkeys(principal.user_id))
    return {"passkeys": keys}


@router.post("/auth/passkeys/register/options")
async def register_options(principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    rp_id, _ = _rp(reg)
    known = await anyio.to_thread.run_sync(lambda: reg.store.passkey_ids(principal.user_id))
    options = generate_registration_options(
        rp_id=rp_id, rp_name=RP_NAME,
        user_id=principal.user_id.encode(), user_name=principal.email, user_display_name=principal.name or principal.email,
        # Resident so signing in later needs no email typed first, and verified so the key means "this person",
        # not merely "this device".
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=_b64(cid)) for cid in known],
    )
    return {"handle": _challenges.issue(options.challenge, principal.user_id), "options": json.loads(options_to_json(options))}


@router.post("/auth/passkeys/register/verify", status_code=201)
async def register_verify(body: Answer, principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    opened = _challenges.spend(body.handle)
    if opened is None or opened[1] != principal.user_id:
        raise HTTPException(status_code=400, detail="That took too long. Try adding the passkey again.")
    rp_id, origins = _rp(reg)
    try:
        ok = verify_registration_response(credential=body.credential, expected_challenge=opened[0],
                                          expected_rp_id=rp_id, expected_origin=origins)
    except (WebAuthnException, ValueError, KeyError) as exc:
        # Anything the library refuses — a bad signature, a mangled body — is the client's problem, not a crash.
        log.info("passkey registration rejected: %s", exc)
        raise HTTPException(status_code=400, detail="That passkey could not be verified.") from exc
    transports = ",".join(body.credential.get("response", {}).get("transports") or []) or None
    saved = await anyio.to_thread.run_sync(lambda: reg.store.add_passkey(
        principal.user_id, credential_id=_b64url(ok.credential_id), public_key=ok.credential_public_key,
        sign_count=ok.sign_count, label=body.label, transports=transports))
    return {"passkey": saved}


@router.delete("/auth/passkeys/{passkey_id}")
async def delete_passkey(passkey_id: int, principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    gone = await anyio.to_thread.run_sync(lambda: reg.store.delete_passkey(principal.user_id, passkey_id))
    if not gone:
        raise HTTPException(status_code=404, detail="No such passkey.")
    return {"deleted": True}


# ------------------------------------------------------------------ signing in with one


@router.post("/auth/passkeys/login/options")
async def login_options(reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """No email, no allow-list: the browser offers whichever passkey it holds for this site, and the credential
    it returns says who it belongs to."""
    rp_id, _ = _rp(reg)
    options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.PREFERRED)
    return {"handle": _challenges.issue(options.challenge), "options": json.loads(options_to_json(options))}


@router.post("/auth/passkeys/login/verify")
async def login_verify(body: Answer, request: Request, reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    ip = request.client.host if request.client else "?"
    if _limiter.blocked(ip):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes.")
    _limiter.hit(ip)

    opened = _challenges.spend(body.handle)
    if opened is None:
        raise HTTPException(status_code=400, detail="That took too long. Try signing in again.")
    credential_id = str(body.credential.get("id") or "")
    stored = await anyio.to_thread.run_sync(lambda: reg.store.find_passkey(credential_id))
    if stored is None:
        raise HTTPException(status_code=401, detail="That passkey is not registered here.")

    rp_id, origins = _rp(reg)
    try:
        ok = verify_authentication_response(
            credential=body.credential, expected_challenge=opened[0], expected_rp_id=rp_id, expected_origin=origins,
            credential_public_key=stored["public_key"], credential_current_sign_count=stored["sign_count"])
    except (WebAuthnException, ValueError, KeyError) as exc:
        log.info("passkey sign-in rejected from %s: %s", ip, exc)
        raise HTTPException(status_code=401, detail="That passkey could not be verified.") from exc

    profile = await anyio.to_thread.run_sync(lambda: reg.store.get_profile(stored["user_id"]))
    if profile is None:
        raise HTTPException(status_code=401, detail="That account no longer exists.")
    await anyio.to_thread.run_sync(lambda: reg.store.touch_passkey(stored["id"], ok.new_sign_count))
    _limiter.clear(ip)
    log.info("passkey sign-in: %s", profile.email)
    return _session(reg, profile)


def _b64url(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64(value: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
