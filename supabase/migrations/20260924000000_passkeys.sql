-- Passkeys: signing in with the device's own screen lock instead of a password.
--
-- A credential is a public key the browser's authenticator generated for this site, plus the counter it reports.
-- No secret of ours lives here: the private half never leaves the device, and this row is useless to anyone who
-- reads it. `sign_count` is the authenticator's own replay counter, checked and raised on every sign-in.
create table if not exists public.passkeys (
  id            bigserial primary key,
  user_id       uuid not null references public.profiles(id) on delete cascade,
  credential_id text not null unique,               -- base64url, as the browser reports it
  public_key    bytea not null,
  sign_count    bigint not null default 0,
  transports    text,
  label         text,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz
);
create index if not exists passkeys_user on public.passkeys (user_id);

-- No policies, and no grant to `authenticated`: passkeys are read before anyone is signed in, so the API reads
-- them on the admin connection the same way it reads local_users. RLS on with nothing granted keeps a tenant
-- connection — and so anything reached through MCP — from seeing them at all.
alter table public.passkeys enable row level security;
