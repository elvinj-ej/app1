-- ============================================================
-- AWS Consumption Tracker Schema
-- Run this in Supabase SQL editor (Dashboard → SQL Editor → New query)
-- ============================================================

-- Extend profiles with role
alter table public.profiles add column if not exists email text;
alter table public.profiles add column if not exists role text not null default 'user' check (role in ('admin', 'user'));

-- Auto-populate email on profile creation
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, new.raw_user_meta_data->>'display_name')
  on conflict (id) do update set email = new.email;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ── Workloads ────────────────────────────────────────────────
-- Workloads from the Exclusion tab; everything not listed here = "Others"
create table if not exists public.workloads (
  id              bigserial primary key,
  name            text not null unique,
  owner_user_id   uuid references public.profiles(id) on delete set null,
  owner_name      text,
  owner_email     text,
  aws_account_id  text,
  category        text,
  -- true = shared networking workload (AWS Networks, Billing, Network F5, Network Firewall)
  -- their monthly costs are distributed proportionally across all non-networking workloads
  is_networking   boolean not null default false,
  is_active       boolean not null default true,
  created_at      timestamptz default now()
);

-- ── Monthly Workload Consumption ─────────────────────────────
-- One row per workload per month.
-- fy_year: fiscal year start (e.g. 2025 = FY26, Jul 2025 – Jun 2026)
-- month_in_fy: 1 = July, 2 = Aug, ..., 12 = June
create table if not exists public.workload_monthly (
  id                      bigserial primary key,
  workload_id             bigint not null references public.workloads(id) on delete cascade,
  fy_year                 int not null,
  month_in_fy             int not null check (month_in_fy between 1 and 12),
  cur_amount              numeric(14,2) default 0,      -- raw CUR data amount
  forecast_amount         numeric(14,2) default 0,      -- admin-entered forecast
  invoiced_amount         numeric(14,2),                -- from Telstra invoice (null until received)
  networking_share        numeric(14,2) default 0,      -- allocated share of networking
  invoice_adjustment_share numeric(14,2) default 0,    -- allocated share of invoice diff
  status                  text not null default 'forecast' check (status in ('forecast', 'invoiced')),
  updated_at              timestamptz default now(),
  unique (workload_id, fy_year, month_in_fy)
);

create index if not exists wm_workload_period on public.workload_monthly (workload_id, fy_year, month_in_fy);
create index if not exists wm_period on public.workload_monthly (fy_year, month_in_fy);

-- ── Networking Costs ─────────────────────────────────────────
-- Shared networking lines (rows A17-A20 in AWS Run Cost tab)
-- Stored as individual line items then summed per period
create table if not exists public.networking_costs (
  id            bigserial primary key,
  fy_year       int not null,
  month_in_fy   int not null check (month_in_fy between 1 and 12),
  description   text,
  amount        numeric(14,2) not null default 0,
  created_at    timestamptz default now(),
  unique (fy_year, month_in_fy, description)
);

-- ── Invoice Adjustments ──────────────────────────────────────
-- The small invoice difference per month (U16, Z16, AE16 pattern in Excel)
create table if not exists public.invoice_adjustments (
  id            bigserial primary key,
  fy_year       int not null,
  month_in_fy   int not null check (month_in_fy between 1 and 12),
  amount        numeric(14,2) not null default 0,
  description   text,
  created_at    timestamptz default now(),
  unique (fy_year, month_in_fy)
);

-- ── CUR Uploads ──────────────────────────────────────────────
-- Track bi-weekly CUR file uploads
create table if not exists public.cur_uploads (
  id            bigserial primary key,
  uploaded_by   uuid references public.profiles(id) on delete set null,
  period_start  date not null,
  period_end    date not null,
  filename      text,
  row_count     int,
  processed     boolean default false,
  data          jsonb not null default '[]',
  created_at    timestamptz default now()
);

-- ── Row Level Security ───────────────────────────────────────
alter table public.workloads          enable row level security;
alter table public.workload_monthly   enable row level security;
alter table public.networking_costs   enable row level security;
alter table public.invoice_adjustments enable row level security;
alter table public.cur_uploads        enable row level security;

-- Helper: is the current user an admin?
create or replace function public.is_admin()
returns boolean language sql security definer as $$
  select exists (
    select 1 from public.profiles where id = auth.uid() and role = 'admin'
  );
$$;

-- Workloads: everyone can read, only admins can write
create policy "workloads_read"   on public.workloads for select using (true);
create policy "workloads_admin"  on public.workloads for all using (public.is_admin());

-- Monthly data: admins see all, users see only their own workloads
create policy "wm_admin"   on public.workload_monthly for all using (public.is_admin());
create policy "wm_own"     on public.workload_monthly for select
  using (
    exists (
      select 1 from public.workloads w
      where w.id = workload_id and w.owner_user_id = auth.uid()
    )
  );

-- Shared cost tables: admins write, everyone reads
create policy "nc_read"   on public.networking_costs    for select using (true);
create policy "nc_admin"  on public.networking_costs    for all    using (public.is_admin());
create policy "ia_read"   on public.invoice_adjustments for select using (true);
create policy "ia_admin"  on public.invoice_adjustments for all    using (public.is_admin());
create policy "cur_read"  on public.cur_uploads         for select using (public.is_admin());
create policy "cur_admin" on public.cur_uploads         for all    using (public.is_admin());

-- ── Useful View ──────────────────────────────────────────────
-- Total effective monthly consumption per workload
create or replace view public.workload_consumption as
select
  wm.id,
  wm.workload_id,
  w.name as workload_name,
  w.owner_name,
  w.owner_email,
  w.owner_user_id,
  w.category,
  wm.fy_year,
  wm.month_in_fy,
  -- calendar month/year
  case when wm.month_in_fy <= 6
    then wm.fy_year + 1
    else wm.fy_year
  end as calendar_year,
  case wm.month_in_fy
    when 1 then 7 when 2 then 8 when 3 then 9 when 4 then 10
    when 5 then 11 when 6 then 12 when 7 then 1 when 8 then 2
    when 9 then 3 when 10 then 4 when 11 then 5 when 12 then 6
  end as calendar_month,
  wm.cur_amount,
  wm.forecast_amount,
  wm.invoiced_amount,
  wm.networking_share,
  wm.invoice_adjustment_share,
  wm.status,
  -- effective total: use invoiced if available, else forecast
  coalesce(wm.invoiced_amount, wm.forecast_amount) + wm.networking_share + wm.invoice_adjustment_share as effective_total
from public.workload_monthly wm
join public.workloads w on w.id = wm.workload_id;
