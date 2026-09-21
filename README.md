# FinMCP

A personal finance tracker whose brain is an [MCP](https://modelcontextprotocol.io) server.

You track money in a calm web app: add an expense in plain words, see what you have spent, what you can still spend and what is coming up, keep budgets honest, save towards goals. The interesting part is underneath: every one of those features is an MCP tool. The web app is the first client. Claude Desktop, Claude Code, Cursor and the in-app assistant are the others, and they all talk to the same ledger with the same rules.

```
Web app ──┐
Assistant ─┤                        ┌── categorisation memory
Claude Desktop ─┼──► FinMCP MCP server ├── budgets, recurring detection, goals
Claude Code ────┤   (27 tools, 13 resources, 4 prompts)   ├── statement / receipt / SMS parsing
Cursor, scripts ┘                        └── read-only SQL over your rows
                              │
                              ▼
                 Postgres (Supabase or embedded local)
                 one row-level-security policy per account
```

## Why MCP

The useful part of a finance tool is its logic: dedupe imports by fingerprint, remember that "SWIGGY*ORDER 8812" is Food & Dining, project a budget to month end, spot that Netflix lands on the 12th. Write that once, behind the Model Context Protocol, and:

- **Any AI host becomes a front end.** Ask Claude Desktop "what did I spend on food last month?" or tell Claude Code "add 450 for Swiggy" and it calls `get_summary` or `add_transaction`, exactly what the app's own buttons call.
- **The rules live in one place.** A tool call from an external client is categorised, deduplicated, budget-checked and audited by the same server code as a tap in the app. There is no second implementation to drift.
- **Every action is attributed.** The server records which client made each write (`web`, `assistant`, `Claude Desktop`, ...). The Activity screen is the MCP audit trail; the Connect screen shows which clients have touched the ledger.
- **Isolation is the database's job.** Every request opens a Postgres transaction as the caller's account with row-level security on, so a tool call from any door can only see that account's rows.

### The whole protocol, inside the app

The app is itself an MCP host: the API opens two in-process MCP clients per account (`finmcp-web` for the screens, `finmcp-assistant` for the chat agent), and the **MCP live** screen draws that architecture and streams every message.

| MCP feature | Direction | What it does here |
|---|---|---|
| Tools (24), resources (12 + a `finmcp://transactions/{month}` template), prompts (4) | client → server | Every screen reads and writes through them; nothing touches the tables directly |
| **Elicitation** | server → client | A weak category guess or a delete pauses the tool call; the app shows the server's question as a dialog and sends the answer back |
| **Sampling** | server → client | Merchants no rule knows go to the app's Claude model in one batched `sampling/createMessage`; the server holds no API key |
| **Roots** | server → client | Statement imports are refused outside the account's upload folder |
| **Subscriptions** (`subscriptions/listen`) | server → client | The web client keeps a stream open; a write from any client (even Claude Desktop) becomes `resources/updated` and the screens refresh |
| Progress and logging | server → client | Imports and bulk categorising report progress; the server narrates what it filed and why |
| Completion | client → server | Month arguments autocomplete for prompts and the resource template |

Server-to-client requests are declared as SDK resolvers (`Resolve`, `Elicit`, `Sample`, `ListRoots` in [finmcp/server.py](finmcp/server.py)), so they work on protocol `2026-07-28` (batched `input_required` rounds) and on `2025-11-25` (standalone requests). The host side lives in [agent/host.py](agent/host.py) (trace, elicitation broker, sampling bridge, roots) and [finmcp/subscriptions.py](finmcp/subscriptions.py) (per-account buses). `tests/test_mcp_features.py` drives each feature end to end.

## What is in the app

| Screen | What it answers | MCP tools behind it |
|---|---|---|
| Home | Spent this month, pace vs last month, safe-to-spend per day, what is coming, three insights | `get_overview`, `get_summary` |
| Transactions | Search, filter, edit, categorise; every correction teaches the categoriser | `list_transactions`, `update_transaction`, `categorize_uncategorized` |
| Budgets | Spend vs limit with month-end projection, one-click suggestions from your 3-month average | `get_budget_summary`, `set_budget`, `check_budget_alerts` |
| Goals | Targets with a deadline and the monthly amount needed | `list_goals`, `upsert_goal`, `add_to_goal` |
| Subscriptions | Bills and subscriptions detected from payment rhythm, next due dates, monthly cost | `list_recurring` |
| Ask | Chat with an agent that picks tools and shows its calls | everything |
| Import | Statement PDFs, CSV exports, receipt photos, SMS dumps | `parse_statement`, `import_statement`, `import_text` |
| Connect | Personal MCP tokens, ready-to-paste client configs, tool catalogue, connected clients | (the server itself) |
| Activity | The audit trail, filterable by client | `recent_activity` |

Quick add lives on every screen: `450 swiggy`, `coffee 120 yesterday`, `+50000 salary`, `uber 340 on 12 sep #transport`. Press `N` to focus it; every add has Undo.

Changes made by any client appear in the app as they happen: the API streams the account's change feed over server-sent events, and Supabase Realtime covers processes that write to Postgres directly.

## Run it

Requirements: Python 3.11+, Node 20+. Nothing else; the first run downloads an embedded PostgreSQL 17 into `data/pgbin/`.

```bash
make setup      # venv + python deps + web deps
make dev        # builds the web app and serves everything on http://127.0.0.1:8000
```

Create an account on the landing page (tick "start with sample data" to get 90 days of realistic transactions), and you are on the Home screen. That is the fully local mode: accounts and the ledger live in the embedded Postgres under `data/`, sessions are JWTs signed with a secret in `data/.jwt-secret`.

Optional: add `ANTHROPIC_API_KEY` to `.env` and the assistant, categoriser, receipt reader and text-to-SQL switch from the deterministic offline engine to Claude.

## Supabase

Free tier is enough. Create a project, then in `.env` (see `.env.example`):

```
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_ANON_KEY=<anon / publishable key>
SUPABASE_DB_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Apply the schema with `make migrate` (or `supabase db push` if you use the Supabase CLI; the migrations live in `supabase/migrations/`), then `make dev`. What changes:

- **Auth** is Supabase Auth: email + password, and any OAuth provider you enable (list them in `SUPABASE_OAUTH_PROVIDERS=google,github` to show the buttons). The API verifies access tokens against the project's JWKS; set `SUPABASE_JWT_SECRET` only for older projects still on the HS256 secret.
- **Ledger** is your Supabase Postgres. The same `Database.tenant()` path applies: `SET LOCAL ROLE authenticated` plus the caller's JWT claims, so the RLS policies in the migration are what protect the rows, the same policies PostgREST and Realtime use.
- **Realtime** (optional): the migration adds `transactions` to the `supabase_realtime` publication, and the web app subscribes to its own rows.
- **Delete account** removes the Supabase Auth user too when `SUPABASE_SERVICE_ROLE_KEY` is set (server-side only).

Local mode and Supabase mode share every line of ledger code; only the identity provider and the connection string differ.

## Deploy

The app runs as one process locally and as two services in production: the React app on Vercel, the API and
MCP endpoint on a container host. Nothing in the ledger code changes — only where the browser sends requests
and which origins the API answers.

**Backend** (`Dockerfile`, port `$PORT` or `7860`). On Render, point a new Blueprint at `render.yaml` and fill
in the secrets it declares; any Docker host works the same way. Set at least:

| Variable | Value |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_DB_URL` | from the Supabase dashboard (use a pooler URL) |
| `FINMCP_PUBLIC_URL` | the deployed API's own URL, e.g. `https://finmcp-api.onrender.com` |
| `FINMCP_CORS_ORIGINS` | the frontend's origin, e.g. `https://finmcp.vercel.app` |
| `FINMCP_DATA_DIR` | a writable path; the image defaults to `/tmp/finmcp-data` |

**Frontend** (`web/vercel.json`). Import the repo on Vercel with **Root Directory** `web`, and set
`VITE_API_BASE` to the backend URL. Left unset, the app calls `/api` on its own origin, which is what the
local single-process build and `make dev` rely on.

A Hugging Face Space works too (`deploy/hf/README.md` carries the Spaces front-matter, `make deploy-hf
SPACE=<user>/<space>` syncs the backend into it) — Docker Spaces need a PRO subscription.

## Connect an MCP client

1. In the app, open **Connect** and create a token (`fm_...`). It is shown once.
2. Pick your client; the snippet is filled in:

```bash
# Claude Code
claude mcp add --transport http finmcp http://127.0.0.1:8000/mcp --header "Authorization: Bearer fm_..."

# Claude Desktop (claude_desktop_config.json), via mcp-remote
{ "mcpServers": { "finmcp": { "command": "npx", "args": ["-y", "mcp-remote", "http://127.0.0.1:8000/mcp", "--header", "Authorization: Bearer fm_..."] } } }

# or let the script write it
python scripts/install_claude_desktop.py --token fm_...
```

3. Ask. "How am I doing this month?" calls `get_overview`. "Which subscriptions can I cut?" uses the `subscription_audit` prompt. Every write shows up in Activity with the client's name.

The endpoint is Streamable HTTP at `/mcp`, bearer-token authenticated, one server for every account: the middleware resolves the token to a principal and the tools read it from the request context. `python -m finmcp --token fm_...` serves the same account over stdio for hosts that launch a process.

## Architecture

```
finmcp/                 the MCP server and everything it owns
  server.py             27 tools, 13 resources, 4 prompts; per-account TenantState; principal from the request
  db/database.py        psycopg pool, migrations, Database.tenant(user_id) = RLS-scoped transaction
  db/repository.py      every SQL statement; writes stamped with the client and published on the change feed
  db/accounts.py        profiles, local password accounts, personal MCP tokens
  db/devpg.py           embedded PostgreSQL for local mode and tests
  services/             summary, budgets, recurring detection, overview, categorisation, text-to-SQL
  ingestion/            PDF / CSV / receipt / SMS parsers with fingerprint dedupe
  llm/                  Claude provider + deterministic fallbacks (keyword rules, rule-based SQL)
agent/                  an MCP client + model driver loop (Claude, or the offline LocalDriver)
api/                    FastAPI: bearer auth (Supabase JWT / local JWT / fm_ tokens), routes are tool calls,
                        /mcp mount with bearer middleware, /api/events SSE change feed
supabase/migrations/    the schema: tables, views, triggers, RLS policies, grants
web/                    React 19 + Vite, react-three-fiber for the landing scenes, motion for scroll effects
```

Security notes: passwords are scrypt-hashed (local mode); MCP tokens are stored as SHA-256 hashes and shown once; `run_sql` and `query_transactions` run inside a read-only, RLS-scoped transaction with a statement timeout and a denylist for session-altering functions; login is rate limited per address.

## Development

```bash
make test       # 164 tests on a throwaway embedded Postgres; each test is its own account, RLS keeps them apart
make lint       # ruff + tsc
make e2e        # stdio server, agent loop, API, remote MCP endpoint over real HTTP
make web        # Vite dev server on :5173 (proxies /api and /mcp to :8000)
make server     # MCP server over stdio for the demo account
make agent      # terminal chat with the agent
python scripts/devpg.py status|start|stop|psql
```

## Configuration

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | Turn on Supabase Auth |
| `SUPABASE_DB_URL` | Postgres connection string (Supabase) |
| `SUPABASE_JWT_SECRET` | Legacy HS256 secret; unnecessary with the newer signing keys |
| `SUPABASE_SERVICE_ROLE_KEY` | Optional, lets account deletion remove the auth user |
| `SUPABASE_OAUTH_PROVIDERS` | Providers to show on the sign-in page (`google,github`) |
| `FINMCP_DATABASE_URL` | Any Postgres instead of the embedded one |
| `FINMCP_PUBLIC_URL` | Where the API is reachable; used in the Connect snippets |
| `FINMCP_JWT_SECRET` | Local-mode session signing secret (auto-generated) |
| `FINMCP_PG_PORT` | Embedded Postgres port (54329) |
| `ANTHROPIC_API_KEY`, `FINMCP_MODEL`, `FINMCP_LLM`, `FINMCP_AGENT_DRIVER` | Claude settings |
| `FINMCP_CURRENCY` | Default currency for new accounts |
