-- EMIs: loans repaid in fixed monthly instalments (phone on no-cost EMI, a car loan, a home loan).
create table if not exists public.emis (
  id            bigserial primary key,
  user_id       uuid not null,
  name          text not null,
  lender        text,
  amount        numeric(14, 2) not null check (amount > 0),
  start_date    date not null,
  tenure_months integer not null check (tenure_months between 1 and 480),
  principal     numeric(14, 2) check (principal is null or principal > 0),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists emis_user_idx on public.emis (user_id);

drop trigger if exists trg_emis_updated on public.emis;
create trigger trg_emis_updated before update on public.emis
  for each row execute function finmcp.touch_updated_at();

alter table public.emis enable row level security;
drop policy if exists "own rows" on public.emis;
create policy "own rows" on public.emis for all to authenticated
  using (user_id = finmcp.uid()) with check (user_id = finmcp.uid());

grant select, insert, update, delete on public.emis to authenticated;
grant usage, select on all sequences in schema public to authenticated;
