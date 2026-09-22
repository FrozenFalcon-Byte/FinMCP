-- Autopay: a standing instruction for a bill the detector already found.
--
-- The subscription list is derived from history and stays that way; this table only remembers which of those the
-- account has asked us to keep filing on its own. `next_due` is the cycle we owe, `last_posted_on` is the last one
-- we filed, and `posted_count` is how many this rule has written — kept here rather than counted from the ledger so
-- a transaction edited or deleted by hand does not change the rule's own history.
create table if not exists public.autopay (
  id             bigserial primary key,
  user_id        uuid not null,
  merchant_key   text not null,
  merchant       text not null,
  amount         numeric(14, 2) not null check (amount > 0),
  cadence        text not null,
  cadence_days   integer not null check (cadence_days between 1 and 400),
  category       text,
  next_due       date not null,
  active         boolean not null default true,
  posted_count   integer not null default 0,
  last_posted_on date,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create unique index if not exists autopay_user_merchant on public.autopay (user_id, merchant_key);
create index if not exists autopay_due on public.autopay (user_id, next_due) where active;

drop trigger if exists trg_autopay_updated on public.autopay;
create trigger trg_autopay_updated before update on public.autopay
  for each row execute function finmcp.touch_updated_at();

alter table public.autopay enable row level security;
drop policy if exists "own rows" on public.autopay;
create policy "own rows" on public.autopay for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

grant select, insert, update, delete on public.autopay to authenticated;
grant usage, select on all sequences in schema public to authenticated;
