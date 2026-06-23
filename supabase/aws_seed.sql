-- ============================================================
-- Seed: Known workloads from the Exclusion tab
-- The 4 networking workloads are flagged is_networking = true;
-- their monthly costs are distributed proportionally to all other workloads.
-- Run AFTER aws_schema.sql
-- ============================================================

alter table public.workloads add column if not exists is_networking boolean not null default false;

-- Insert all 24 tracked workloads (upsert by name)
insert into public.workloads (name, owner_name, category, is_networking, is_active) values
  -- ── Shared networking (rows 17-20 in AWS_Run Cost) ─────
  ('AWS Networks',      'Andy McLaughlin',          'Consumption', true,  true),
  ('Billing',           'Jan Willems',              'Consumption', true,  true),
  ('Network F5',        'Andy McLaughlin',          'Consumption', true,  true),
  ('Network Firewall',  'Andy McLaughlin',          'Consumption', true,  true),

  -- ── Tracked workloads (Exclusion tab) ──────────────────
  ('Boomi-Gateway',     'Joseph Encomienda',        'Consumption', false, true),
  ('Boomi-Integration', 'Joseph Encomienda',        'Consumption', false, true),
  ('Bunker Backups',    'Jan Willems',              'Consumption', false, true),
  ('Clark AI',          'Jiten Shah',               'Project X-charge Cost', false, true),
  ('Clinical Cloud',    'Sam Jarman',               'Consumption', false, true),
  ('CNA',               'Leigh Wells',              'Project X-charge Cost', false, true),
  ('Codacy',            'Dinesh Selvam',            'Consumption', false, true),
  ('Contact Center',    'Andy McLaughlin',          'Consumption', false, true),
  ('DataInsights',      'Jiten Shah',               'Project X-charge Cost', false, true),
  ('DPX MCP',           'Cherry Zhang',             'Consumption', false, true),
  ('MES',               'Rushka Plunkett',          'Project X-charge Cost', false, true),
  ('Network F5',        'Andy McLaughlin',          'Consumption', false, true),  -- duplicate guard handled by upsert
  ('Sonar',             'Jiten Shah',               'Project X-charge Cost', false, true),
  ('Sitecore',          'Dinesh Selvam',            'Consumption', false, true),
  ('MIP',               'Rob Pearson',              'Consumption', false, true),
  ('Olingo Odata',      'Cherry Zhang',             'Consumption', false, true),
  ('Nautilus',          'Roger Calixto',            'Consumption', false, true),
  ('Gitlab',            'Sam Jarman',               'Consumption', false, true),
  ('Shared Services',   'Ignus Swart/Jan Willems',  'Consumption', false, true),
  ('Boomi-Corporate',   'Joseph Encomienda',        'Consumption', false, true),

  -- ── Catch-all for accounts not in Exclusion list ───────
  ('Others',            null,                       'Consumption', false, true)
on conflict (name) do update
  set owner_name    = excluded.owner_name,
      category      = excluded.category,
      is_networking = excluded.is_networking,
      is_active     = excluded.is_active;
