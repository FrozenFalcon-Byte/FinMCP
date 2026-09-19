"""Create (or refresh) a demo account filled with realistic data, for trying the app.

    make demo-account                              # demo@finmcp.dev with a fresh random password
    make demo-account ARGS="--password 'my pass'"  # choose the password
    make account ARGS="--email you@x.com --name You --password 'pass' --empty"   # your own account, no sample data

Also the way in when a reset email never arrives: running it for an existing email sets a new password (Supabase's
built-in mailer only delivers to your Supabase team's addresses, a few per hour, until you add your own SMTP).

With Supabase configured, the account is created through the Supabase Auth admin API (needs SUPABASE_SERVICE_ROLE_KEY)
with the email already confirmed; otherwise it is a local account. Either way the ledger gets 180 days of
transactions, budgets, goals and recurring bills, and the email and password are printed at the end.
Running it again resets the password and tops the data up (imports are deduplicated by fingerprint).
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finmcp.config import load_settings  # noqa: E402
from finmcp.db import database_for  # noqa: E402
from finmcp.db.accounts import AccountStore  # noqa: E402
from finmcp.db.seed import seed_demo_data  # noqa: E402
from finmcp.server import create_server  # noqa: E402


def supabase_user(settings, email: str, password: str, name: str) -> str:
    base = settings.supabase_url.rstrip("/") + "/auth/v1/admin/users"
    key = settings.supabase_service_key
    if not key:
        raise SystemExit("SUPABASE_SERVICE_ROLE_KEY is empty in .env. Copy it from Supabase: Project Settings -> API Keys -> "
                         "the secret key (sb_secret_...) or the legacy service_role key, paste it after SUPABASE_SERVICE_ROLE_KEY= "
                         "and run this again. It stays on this machine; never put it in the web app.")
    # Legacy service_role keys are JWTs and also go in Authorization; the newer sb_secret_ keys ride in apikey alone.
    headers = {"apikey": key} if key.startswith("sb_secret_") else {"apikey": key, "Authorization": f"Bearer {key}"}
    body = {"email": email, "password": password, "email_confirm": True, "user_metadata": {"name": name}}
    with httpx.Client(timeout=20) as http:
        r = http.post(base, json=body, headers=headers)
        if r.status_code in (200, 201):
            return r.json()["id"]
        if r.status_code not in (400, 409, 422):
            raise SystemExit(f"Supabase refused to create the user: {r.status_code} {r.text[:200]}")
        page = 1
        while True:  # already exists: find it and reset its password
            users = http.get(base, params={"page": page, "per_page": 200}, headers=headers).json().get("users", [])
            match = next((u for u in users if (u.get("email") or "").lower() == email), None)
            if match:
                http.put(f"{base}/{match['id']}", json={"password": password, "email_confirm": True}, headers=headers).raise_for_status()
                return match["id"]
            if len(users) < 200:
                raise SystemExit(f"Supabase says {email} exists but it was not found: {r.text[:200]}")
            page += 1


GOALS = (  # name, target, saved, months until due
    ("Emergency fund", 300000, 126000, 10),
    ("Goa trip", 40000, 18500, 3),
    ("New laptop", 120000, 45000, 6),
)


def add_demo_goals(repo) -> int:
    """Savings goals at different stages, added once (existing goals are left as they are)."""
    from datetime import date

    have = {g.name.lower() for g in repo.list_goals()}
    today = date.today()
    for name, target, saved, months in GOALS:
        if name.lower() not in have:
            m = today.month - 1 + months
            due = date(today.year + m // 12, m % 12 + 1, 1).isoformat()
            repo.create_goal(name, target, saved=saved, due=due)
    return len(repo.list_goals())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default="demo@finmcp.dev")
    ap.add_argument("--name", default="Demo User")
    ap.add_argument("--password", help="defaults to a fresh random passphrase")
    ap.add_argument("--days", type=int, default=180, help="days of history to generate")
    ap.add_argument("--empty", action="store_true", help="create the account without sample data")
    args = ap.parse_args()
    email = args.email.strip().lower()
    password = args.password or "-".join(secrets.token_hex(3) for _ in range(3))

    settings = load_settings()
    db = database_for(settings)
    store = AccountStore(db)
    try:
        if settings.supabase_configured:
            user_id = supabase_user(settings, email, password, args.name)
            store.upsert_profile(user_id, email, args.name)
            where = "Supabase Auth"
        else:
            state = store.local_password_state(email=email)
            if state is None:
                user_id = store.create_local_user(email=email, name=args.name, password=password).id
            else:
                user_id = store.set_local_password(state[0], password).id
            where = "local accounts"
        server = create_server(settings, db=db, user_id=user_id, client="seed")
        repo = server.finmcp.tenant().repo  # type: ignore[attr-defined]
        seeded = {} if args.empty else seed_demo_data(repo, days=args.days)
        goals = len(repo.list_goals()) if args.empty else add_demo_goals(repo)
        total = repo.count_transactions()
    finally:
        db.close()

    print(f"\nAccount ready ({where}, email confirmed).")
    print(f"  email:    {email}")
    print(f"  password: {password}")
    if args.empty:
        print(f"  ledger:   {total} transactions, {goals} goals (no sample data added)")
    else:
        print(f"  ledger:   {total} transactions ({seeded.get('inserted', 0)} added now), category budgets, {goals} savings goals, recurring bills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
