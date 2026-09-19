-- FinMCP schema. Applied to Supabase (`supabase db push` or `python scripts/migrate.py`) and to the embedded
-- local PostgreSQL. Idempotent: safe to run again.
--
-- Tenancy model: every ledger row carries user_id. Row Level Security policies scoped to finmcp.uid() apply to the
-- `authenticated` role. The API opens every ledger transaction as `authenticated` with the caller's JWT claims set,
-- exactly like Supabase's PostgREST does, so Postgres itself enforces that an account can only see its own rows —
-- through the API, through the MCP server, through Realtime and through the Supabase client alike.

create schema if not exists finmcp;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
end $$;

-- Let the connecting role (postgres locally, postgres on Supabase) switch to `authenticated` per transaction.
do $$
begin
  begin
    execute format('grant authenticated to %I', current_user);
  exception when others then
    raise notice 'could not grant authenticated to %: %', current_user, sqlerrm;
  end;
end $$;

-- The current account. Reads the JWT claims PostgREST / the API set for the transaction.
create or replace function finmcp.uid() returns uuid
language sql stable
as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'
  )::uuid
$$;
grant usage on schema finmcp to authenticated, anon;
grant execute on function finmcp.uid() to authenticated, anon;

create table if not exists public.schema_migrations (
  version    text primary key,
  applied_at timestamptz not null default now()
);

-- ------------------------------------------------------------------ accounts

create table if not exists public.profiles (
  id           uuid primary key,
  email        text not null,
  name         text not null default '',
  currency     text not null default 'INR',
  created_at   timestamptz not null default now(),
  last_seen_at timestamptz
);

-- Password accounts for the no-Supabase local mode. Unused (empty) when Supabase Auth is configured.
create table if not exists public.local_users (
  id            uuid primary key default gen_random_uuid(),
  email         text not null unique,
  name          text not null,
  password_hash text not null,
  created_at    timestamptz not null default now()
);

-- Personal access tokens that MCP clients (Claude Desktop, Claude Code, Cursor, scripts) present as a bearer token.
create table if not exists public.mcp_tokens (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.profiles(id) on delete cascade,
  name         text not null,
  prefix       text not null,
  token_hash   text not null unique,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  last_client  text
);
create index if not exists mcp_tokens_user on public.mcp_tokens (user_id);

-- ------------------------------------------------------------------ ledger

create table if not exists public.categories (
  id           bigserial primary key,
  user_id      uuid not null,
  name         text not null,
  kind         text not null default 'expense' check (kind in ('expense', 'income', 'transfer')),
  budget_limit numeric(14, 2) check (budget_limit is null or budget_limit >= 0),
  description  text,
  created_at   timestamptz not null default now()
);
create unique index if not exists categories_user_name on public.categories (user_id, lower(name));

create table if not exists public.transactions (
  id                  bigserial primary key,
  user_id             uuid not null,
  date                date not null,
  amount              numeric(14, 2) not null check (amount >= 0),
  direction           text not null default 'debit' check (direction in ('debit', 'credit')),
  currency            text not null default 'INR',
  merchant            text not null,
  description         text,
  category_id         bigint references public.categories(id) on delete set null,
  category_confidence real check (category_confidence is null or (category_confidence >= 0 and category_confidence <= 1)),
  category_source     text check (category_source is null or category_source in ('user', 'memory', 'rule', 'llm', 'import', 'seed')),
  source              text not null default 'manual',
  client              text,
  raw_text            text,
  fingerprint         text,
  needs_review        boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create unique index if not exists transactions_user_fingerprint on public.transactions (user_id, fingerprint) where fingerprint is not null;
create index if not exists transactions_user_date on public.transactions (user_id, date desc, id desc);
create index if not exists transactions_user_category on public.transactions (user_id, category_id);
create index if not exists transactions_user_merchant on public.transactions (user_id, merchant);
create index if not exists transactions_user_review on public.transactions (user_id) where needs_review;

create table if not exists public.merchant_memory (
  user_id      uuid not null,
  merchant_key text not null,
  category_id  bigint not null references public.categories(id) on delete cascade,
  hits         integer not null default 1,
  last_seen    timestamptz not null default now(),
  primary key (user_id, merchant_key)
);

create table if not exists public.audit_log (
  id        bigserial primary key,
  user_id   uuid not null,
  ts        timestamptz not null default now(),
  actor     text not null,
  client    text,
  action    text not null,
  entity    text,
  entity_id bigint,
  detail    jsonb
);
create index if not exists audit_log_user_ts on public.audit_log (user_id, id desc);

create table if not exists public.imports (
  id          bigserial primary key,
  user_id     uuid not null,
  ts          timestamptz not null default now(),
  source_kind text not null,
  source_name text,
  parsed      integer not null default 0,
  inserted    integer not null default 0,
  duplicates  integer not null default 0,
  detail      jsonb
);

create table if not exists public.goals (
  id         bigserial primary key,
  user_id    uuid not null,
  name       text not null,
  target     numeric(14, 2) not null check (target > 0),
  saved      numeric(14, 2) not null default 0 check (saved >= 0),
  due        date,
  icon       text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ------------------------------------------------------------------ views

create or replace view public.v_transactions with (security_invoker = true) as
  select t.id, t.user_id, t.date, t.amount, t.direction, t.currency, t.merchant, t.description,
         t.category_id, c.name as category, c.kind as category_kind,
         t.category_confidence, t.category_source, t.source, t.client, t.raw_text, t.fingerprint,
         t.needs_review, t.created_at, t.updated_at
  from public.transactions t
  left join public.categories c on c.id = t.category_id;

create or replace view public.monthly_summary with (security_invoker = true) as
  select t.user_id,
         to_char(t.date, 'YYYY-MM') as month,
         coalesce(c.name, 'Uncategorized') as category,
         coalesce(c.kind, 'expense') as category_kind,
         sum(case when t.direction = 'debit' then t.amount else 0 end) as spent,
         sum(case when t.direction = 'credit' then t.amount else 0 end) as received,
         count(*) as n
  from public.transactions t
  left join public.categories c on c.id = t.category_id
  group by 1, 2, 3, 4;

-- ------------------------------------------------------------------ triggers

create or replace function finmcp.touch_updated_at() returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists trg_transactions_updated on public.transactions;
create trigger trg_transactions_updated before update on public.transactions
  for each row execute function finmcp.touch_updated_at();
drop trigger if exists trg_goals_updated on public.goals;
create trigger trg_goals_updated before update on public.goals
  for each row execute function finmcp.touch_updated_at();

-- ------------------------------------------------------------------ row level security

alter table public.profiles        enable row level security;
alter table public.local_users     enable row level security;   -- no policies: never visible to authenticated
alter table public.mcp_tokens      enable row level security;
alter table public.categories      enable row level security;
alter table public.transactions    enable row level security;
alter table public.merchant_memory enable row level security;
alter table public.audit_log       enable row level security;
alter table public.imports         enable row level security;
alter table public.goals           enable row level security;

drop policy if exists "own profile" on public.profiles;
create policy "own profile" on public.profiles for all to authenticated
  using (id = finmcp.uid()) with check (id = finmcp.uid());

drop policy if exists "own tokens" on public.mcp_tokens;
create policy "own tokens" on public.mcp_tokens for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

drop policy if exists "own rows" on public.categories;
create policy "own rows" on public.categories for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

drop policy if exists "own rows" on public.transactions;
create policy "own rows" on public.transactions for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

drop policy if exists "own rows" on public.merchant_memory;
create policy "own rows" on public.merchant_memory for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

drop policy if exists "own rows" on public.audit_log;
create policy "own rows" on public.audit_log for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

drop policy if exists "own rows" on public.imports;
create policy "own rows" on public.imports for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

drop policy if exists "own rows" on public.goals;
create policy "own rows" on public.goals for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

grant usage on schema public to authenticated, anon;
grant select, insert, update, delete on
  public.profiles, public.mcp_tokens, public.categories, public.transactions, public.merchant_memory,
  public.audit_log, public.imports, public.goals, public.v_transactions, public.monthly_summary
  to authenticated;
grant usage, select on all sequences in schema public to authenticated;
revoke all on public.local_users from authenticated, anon;
revoke all on public.schema_migrations from authenticated, anon;

-- Supabase Realtime (optional): let the web app subscribe to its own transaction changes.
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.transactions;
    exception when others then
      null; -- already published
    end;
  end if;
end $$;
