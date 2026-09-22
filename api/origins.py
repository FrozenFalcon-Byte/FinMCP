"""Which browser origins this API answers to.

Two things need the same answer and must not disagree: CORS, which decides whose fetch is allowed, and passkeys,
whose relying-party id has to be the domain of the page the person is actually on. The frontend is deployed apart
from the API (Vercel over Render), so neither can be derived from this process's own URL — the operator names them
in FINMCP_CORS_ORIGINS, and dev origins are always allowed.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def cors_origins() -> list[str]:
    """Browser origins allowed to call this API: FINMCP_CORS_ORIGINS, comma separated, plus the dev ones."""
    extra = [o.strip().rstrip("/") for o in os.environ.get("FINMCP_CORS_ORIGINS", "").split(",") if o.strip()]
    return list(dict.fromkeys([*DEV_ORIGINS, *extra]))


def origin_regex() -> str | None:
    return os.environ.get("FINMCP_CORS_ORIGIN_REGEX") or None


def allowed_origin(origin: str | None, *, also: str | None = None) -> str | None:
    """The origin normalised, or None if this deployment does not serve it.

    `also` lets a caller add one more acceptable origin (the API's own public URL) without it having to be in the
    CORS list. An origin that is not allowed here is treated as absent rather than trusted, because the header is
    the browser's claim about the page and nothing more.
    """
    if not origin:
        return None
    o = origin.strip().rstrip("/")
    if not o or not urlparse(o).hostname:
        return None
    allowed = cors_origins()
    if also:
        allowed.append(also.rstrip("/"))
    if o in allowed:
        return o
    pattern = origin_regex()
    if pattern and re.fullmatch(pattern, o):
        return o
    return None
