-- First run: what a person tells us before the dashboard can mean anything, and a photo to go with it.
-- Until onboarded_at is set the app shows the setup instead of the dashboard, so this is also the gate.

alter table public.profiles add column if not exists avatar         text;          -- small square data URL, capped by the API
alter table public.profiles add column if not exists monthly_income numeric(14,2); -- take-home, in the profile currency
alter table public.profiles add column if not exists pay_day        smallint;      -- 1-31, the day it lands
alter table public.profiles add column if not exists keep_pct       smallint;      -- share of income to hold back each month
alter table public.profiles add column if not exists onboarded_at   timestamptz;
alter table public.profiles add column if not exists tour_seen_at   timestamptz;

-- Accounts that already have a ledger were never asked, and should not be stopped on their way in.
update public.profiles p set onboarded_at = coalesce(p.onboarded_at, now())
where exists (select 1 from public.transactions t where t.user_id = p.id);
