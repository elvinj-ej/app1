-- ============================================================
-- Fitness Tracker Schema
-- Run this in Supabase SQL editor (Dashboard → SQL Editor → New query)
-- ============================================================

-- Users are managed by Supabase Auth — this extends the auth.users table
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  timezone    text default 'UTC',
  created_at  timestamptz default now()
);

-- ── Body Weight ──────────────────────────────────────────────
create table if not exists public.body_weight (
  id          bigserial primary key,
  user_id     uuid not null references public.profiles(id) on delete cascade,
  date        date not null,
  weight_kg   numeric(5,2) not null,
  source      text not null check (source in ('apple_health', 'manual', 'garmin')),
  created_at  timestamptz default now(),
  unique (user_id, date, source)
);

create index if not exists body_weight_user_date on public.body_weight (user_id, date desc);

-- ── Garmin Daily Summaries ───────────────────────────────────
create table if not exists public.garmin_daily (
  id                    bigserial primary key,
  user_id               uuid not null references public.profiles(id) on delete cascade,
  date                  date not null,
  total_kcal            int,
  active_kcal           int,
  bmr_kcal              int,
  total_steps           int,
  distance_meters       int,
  avg_heart_rate        int,
  synced_at             timestamptz default now(),
  unique (user_id, date)
);

create index if not exists garmin_daily_user_date on public.garmin_daily (user_id, date desc);

-- ── Hevy Workouts ────────────────────────────────────────────
create table if not exists public.workouts (
  id            bigserial primary key,
  user_id       uuid not null references public.profiles(id) on delete cascade,
  hevy_id       text not null,
  title         text,
  description   text,
  start_time    timestamptz not null,
  end_time      timestamptz,
  exercises     jsonb not null default '[]',  -- full exercise/set data
  volume_kg     numeric(10,2),               -- pre-computed total volume
  total_sets    int,
  total_reps    int,
  synced_at     timestamptz default now(),
  unique (user_id, hevy_id)
);

create index if not exists workouts_user_start on public.workouts (user_id, start_time desc);

-- ── Meals ────────────────────────────────────────────────────
create table if not exists public.meals (
  id              bigserial primary key,
  user_id         uuid not null references public.profiles(id) on delete cascade,
  logged_at       timestamptz not null default now(),
  date            date not null generated always as (logged_at::date) stored,
  photo_url       text,                  -- path in Supabase Storage
  description     text,                  -- Claude's description of the meal
  calories        int not null default 0,
  protein_g       numeric(6,2) not null default 0,
  carbs_g         numeric(6,2) not null default 0,
  fat_g           numeric(6,2) not null default 0,
  items           jsonb not null default '[]',  -- per-item breakdown
  confidence_note text,
  user_corrected  boolean default false   -- true if user edited AI estimate
);

create index if not exists meals_user_date on public.meals (user_id, date desc);

-- ── Daily Totals View ────────────────────────────────────────
-- Convenience view joining all sources for a given day
create or replace view public.daily_summary as
select
  coalesce(g.user_id, w.user_id, m.user_id, bw.user_id) as user_id,
  coalesce(g.date, w.date, m.date, bw.date) as date,
  g.total_kcal          as garmin_total_kcal,
  g.active_kcal         as garmin_active_kcal,
  g.total_steps,
  bw.weight_kg,
  bw.source             as weight_source,
  coalesce(m.meal_calories, 0) as total_meal_calories,
  coalesce(m.total_protein_g, 0) as total_protein_g,
  coalesce(m.total_carbs_g, 0)   as total_carbs_g,
  coalesce(m.total_fat_g, 0)     as total_fat_g,
  coalesce(m.meal_count, 0)      as meal_count,
  coalesce(w.workout_count, 0)   as workout_count,
  coalesce(w.total_volume_kg, 0) as workout_volume_kg
from public.garmin_daily g
full outer join (
  select user_id, start_time::date as date,
    count(*) as workout_count,
    sum(volume_kg) as total_volume_kg
  from public.workouts group by user_id, date
) w on g.user_id = w.user_id and g.date = w.date
full outer join (
  select user_id, date,
    sum(calories)  as meal_calories,
    sum(protein_g) as total_protein_g,
    sum(carbs_g)   as total_carbs_g,
    sum(fat_g)     as total_fat_g,
    count(*)       as meal_count
  from public.meals group by user_id, date
) m on coalesce(g.user_id, w.user_id) = m.user_id
   and coalesce(g.date, w.date) = m.date
full outer join public.body_weight bw
  on coalesce(g.user_id, w.user_id, m.user_id) = bw.user_id
 and coalesce(g.date, w.date, m.date) = bw.date;

-- ── Row Level Security ───────────────────────────────────────
alter table public.profiles    enable row level security;
alter table public.body_weight enable row level security;
alter table public.garmin_daily enable row level security;
alter table public.workouts    enable row level security;
alter table public.meals       enable row level security;

-- Each user can only see/modify their own rows
create policy "own profile"     on public.profiles    for all using (auth.uid() = id);
create policy "own weights"     on public.body_weight for all using (auth.uid() = user_id);
create policy "own garmin"      on public.garmin_daily for all using (auth.uid() = user_id);
create policy "own workouts"    on public.workouts    for all using (auth.uid() = user_id);
create policy "own meals"       on public.meals       for all using (auth.uid() = user_id);

-- Auto-create profile row when a new user signs up
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (id) values (new.id) on conflict do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
