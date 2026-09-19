"""Sign-in for the web app.

Supabase mode: the browser talks to Supabase Auth directly (supabase-js) and sends the access token here.
Local mode: this router owns registration and password login and issues its own JWTs. Both end in /auth/me."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from finmcp.db.accounts import MIN_PASSWORD, Principal, Profile
from finmcp.server import seed_account

from ..auth import LOCAL_TTL
from ..deps import AppContext, Registry, get_ctx, get_registry, require_principal

log = logging.getLogger("finmcp.api.auth")
router = APIRouter(tags=["auth"])


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    sample_data: bool = True


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _session(reg: Registry, profile: Profile) -> dict[str, Any]:
    return {"access_token": reg.auth.issue_local_token(profile), "token_type": "bearer", "expires_in": LOCAL_TTL, "user": profile.public()}


@router.get("/auth/config")
async def auth_config(reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """Public: tells the web app how to sign people in."""
    s = reg.settings
    return {
        "mode": reg.auth.mode,
        "supabase_url": s.supabase_url if reg.auth.mode == "supabase" else None,
        "supabase_anon_key": s.supabase_anon_key if reg.auth.mode == "supabase" else None,
        "oauth_providers": list(s.oauth_providers) if reg.auth.mode == "supabase" else [],
        "min_password": MIN_PASSWORD,
        "public_url": s.public_url,
        "mcp_endpoint": f"{s.public_url}/mcp",
    }


@router.post("/auth/register", status_code=201)
async def register(body: RegisterBody, request: Request, reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    if reg.auth.mode != "local":
        raise HTTPException(400, "Accounts are managed by Supabase Auth here; sign up from the app.")
    key = f"signup|{_client_ip(request)}"
    if reg.signup_limiter.blocked(key):
        raise HTTPException(429, "Too many sign-ups from this address. Try again later.")
    reg.signup_limiter.hit(key)
    try:
        profile = await anyio.to_thread.run_sync(lambda: reg.store.create_local_user(email=body.email, name=body.name, password=body.password))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    principal = Principal(user_id=profile.id, email=profile.email, name=profile.name, via="local")
    ctx = await reg.context_for(principal)
    seeded = None
    if body.sample_data:
        seeded = await anyio.to_thread.run_sync(lambda: seed_account(ctx.connection.target, only_if_empty=True))
    return {**_session(reg, profile), "sample_data": seeded is not None}


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    if reg.auth.mode != "local":
        raise HTTPException(400, "Accounts are managed by Supabase Auth here; sign in from the app.")
    key = f"login|{_client_ip(request)}|{body.email.strip().lower()}"
    if reg.login_limiter.blocked(key):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    profile = await anyio.to_thread.run_sync(reg.store.authenticate_local, body.email, body.password)
    if profile is None:
        reg.login_limiter.hit(key)
        raise HTTPException(401, "Email or password is incorrect.")
    reg.login_limiter.clear(key)
    return _session(reg, profile)


class ForgotBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetBody(BaseModel):
    token: str = Field(min_length=20, max_length=2000)
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/password/forgot")
async def forgot_password(body: ForgotBody, request: Request, reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """Local mode: mint a reset link. There is no mail server in local mode, so the link goes to the API log (the
    operator's console) and never into the response, which would let anyone reset anyone. Supabase mode sends the
    email from Supabase Auth directly in the browser."""
    if reg.auth.mode != "local":
        raise HTTPException(400, "Password resets are sent by Supabase Auth here.")
    key = f"forgot|{_client_ip(request)}"
    if reg.login_limiter.blocked(key):
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    reg.login_limiter.hit(key)
    state = await anyio.to_thread.run_sync(lambda: reg.store.local_password_state(email=body.email))
    if state is not None:
        token = reg.auth.issue_reset_token(*state)
        log.warning("Password reset link for %s (valid 30 minutes): %s/reset-password?token=%s", body.email.strip().lower(),
                    reg.settings.public_url.rstrip("/"), token)
    return {"sent": True}


@router.post("/auth/password/reset")
async def reset_password(body: ResetBody, reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    if reg.auth.mode != "local":
        raise HTTPException(400, "Password resets are handled by Supabase Auth here.")
    user_id = await anyio.to_thread.run_sync(reg.auth.reset_subject, body.token)
    if user_id is None:
        raise HTTPException(400, "This reset link has expired or was already used. Ask for a new one.")
    try:
        profile = await anyio.to_thread.run_sync(reg.store.set_local_password, user_id, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    reg.forget(user_id)
    return _session(reg, profile)


@router.post("/auth/logout")
async def logout() -> dict[str, Any]:
    """Sessions are bearer tokens; the client forgets it (and calls supabase.auth.signOut() in Supabase mode)."""
    return {"signed_out": True}


_warming: set[asyncio.Task[Any]] = set()


@router.get("/auth/me")
async def me(principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    profile = await anyio.to_thread.run_sync(reg.auth.ensure_profile, principal.user_id, principal.email, principal.name)
    if principal.user_id not in reg.contexts:
        # The app asks this first on every load: open the account's MCP sessions now, while the page is still loading.
        task = asyncio.create_task(reg.context_for(principal))
        _warming.add(task)
        task.add_done_callback(lambda t: (_warming.discard(t), t.cancelled() or t.exception()))
    return {"user": profile.public(), "via": principal.via}


@router.patch("/auth/profile")
async def update_profile(body: ProfilePatch, principal: Principal = Depends(require_principal), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    try:
        profile = await anyio.to_thread.run_sync(lambda: reg.store.update_profile(principal.user_id, name=body.name, currency=body.currency))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    reg.forget(principal.user_id)  # currency and name feed the per-account servers
    return {"user": profile.public()}


@router.post("/auth/seed-demo")
async def seed_demo(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Fill an empty ledger with 90 days of realistic sample data (no-op when the ledger has transactions)."""
    result = await anyio.to_thread.run_sync(lambda: seed_account(ctx.connection.target, only_if_empty=True))
    return {"seeded": result is not None, "result": result}


async def _delete_supabase_user(reg: Registry, user_id: str) -> bool:
    s = reg.settings
    if reg.auth.mode != "supabase" or not s.supabase_service_key or not s.supabase_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.delete(f"{s.supabase_url}/auth/v1/admin/users/{user_id}",
                                    headers={"apikey": s.supabase_service_key, "Authorization": f"Bearer {s.supabase_service_key}"})
        return r.status_code in {200, 204}
    except httpx.HTTPError as exc:
        log.warning("Supabase admin delete failed: %s", exc)
        return False


@router.delete("/auth/account")
async def delete_account(ctx: AppContext = Depends(get_ctx), reg: Registry = Depends(get_registry)) -> dict[str, Any]:
    """Erase the ledger, tokens and profile. In Supabase mode the auth user is removed too when a service key is configured."""
    tenant = ctx.connection.target.finmcp.tenant()  # type: ignore[attr-defined]
    counts = await anyio.to_thread.run_sync(tenant.repo.erase_ledger)
    await anyio.to_thread.run_sync(reg.store.delete_profile, ctx.user_id)
    removed_auth = await _delete_supabase_user(reg, ctx.user_id)
    reg.forget(ctx.user_id)
    return {"deleted": True, "rows": counts, "auth_user_deleted": removed_auth or reg.auth.mode == "local"}
