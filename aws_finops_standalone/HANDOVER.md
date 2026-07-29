# AWS FinOps Tracker — Project Handover

## Overview

A self-hosted internal web app for tracking AWS cloud costs against Telstra invoices and internal budgets. Built with **Flask + SQLite + Waitress**, served at `http://<host>:4020/AWSFinOps`.

The app is a **single-page application** — one HTML file, four Python modules, one SQLite database. No build step, no frontend framework, no external dependencies beyond the Python packages listed below.

---

## File Structure

```
aws_finops_standalone/
├── app.py              Flask app + all API routes + AD auth
├── aws_db.py           DB schema, seed data, migrations
├── aws_run_cost.py     Three-tier cost model computation
├── aws_ingestor.py     CUR file parser (CSV / Excel)
├── index.html          Single-page UI (served as Flask template)
├── aws_finops.db       SQLite database (created on first run)
├── app.log             Application log (auto-created)
└── HANDOVER.md         This document
```

---

## How to Run

### Requirements

```
flask
waitress
openpyxl        # Excel CUR uploads
werkzeug
```

Install: `pip install flask waitress openpyxl werkzeug`

### Start the server

```bash
python app.py
```

Access at: `http://localhost:4020/AWSFinOps`

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `AWS_DATA_ROOT` | `C:\AWSFinOps\Data` | Root folder for DB and tmp files |
| `AWS_DB_PATH` | `<DATA_ROOT>\db\aws_finops.db` | SQLite database path |
| `AD_ENABLED` | `true` | Set to `false` to bypass AD login (local dev) |
| `AD_DOMAIN` | `COCHLEAR` | Active Directory domain |
| `AD_GROUP` | `Domain Users` | AD group required for access |
| `SECRET_KEY` | `change-this-...` | Flask session secret — change in prod |
| `SSO_SECRET` | `aws-finops-sso-...` | HMAC secret for SSO token — change in prod |

### Data Folder Layout

```
C:\AWSFinOps\Data\
├── db\
│   └── aws_finops.db
└── tmp\            ← transient upload staging (auto-cleaned)
```

---

## Architecture

### Three-Tier Cost Model (`aws_run_cost.py`)

All financial logic lives here. The `compute(month)` function returns a full breakdown for a given month.

```
┌─────────────────────────────────────────────────────────┐
│  Shared Cost accounts (AWS Networks, Billing,           │
│  Network F5, Network Firewall)                          │
│  → Their spend is pooled (shared_pool)                  │
│  → They do NOT receive telstra_diff themselves          │
└─────────────────────┬───────────────────────────────────┘
                      │ distributed proportionally
          ┌───────────▼──────────────┐
          │   Run Cost (Consumption) │  ← each workload row:
          │   Project X-charge       │    actual + shared_alloc + telstra_diff
          │   Other (grouped)        │    = FinOps Total
          └──────────────────────────┘
```

**Key formulas:**

```python
# For each Run/Project/Other workload:
actual        = expense + marketplace + marketplace_adjustment
ratio         = actual / run_proj_total
shared_alloc  = shared_pool × ratio
telstra_diff  = telstra_diff_total × ratio
finops_total  = actual + shared_alloc + telstra_diff
deviation     = finops_total − budget

# Telstra diff (spread across workloads):
effective_invoice  = telstra_invoice + total_adj   # adj is negative for PO purchases
telstra_diff_total = effective_invoice − total_cur

# Grand Total:
grand_total = sum(Run finops_total) + sum(Project finops_total)
# Grand Total should equal telstra_invoice when CUR data is complete
```

**Workload categories:**

| Category | Behaviour |
|---|---|
| `Shared` | Spend pooled and distributed to Run+Project. No deviation calculated. |
| `Consumption` | Individual rows in Run Cost table. Gets shared_alloc + telstra_diff. |
| `Project` | Individual rows in Project X-charge table. Same formula as Consumption. |
| `Other` | Matched from CUR but shown as one aggregated row in Run Cost table. Listed individually in the Workload tab. |

### Tag Matching (`aws_run_cost.py → resolve()`)

CUR data rows carry a `workloads_tag` field. The resolver maps this tag to a workload in three steps:

1. **CUR Tag Override** — if the workload has a `cur_tag` set, match on that (case-insensitive)
2. **Exact name match** — `workloads_tag == workload.name`
3. **Case-insensitive name match** — `workloads_tag.lower() == workload.name.lower()`

Anything that doesn't resolve goes into the "Other" bucket.

### Marketplace Adjustments

Used when a marketplace purchase is paid via a separate PO (outside the Telstra invoice scope). A **negative adjustment** on a workload reduces both that workload's `actual` and the `effective_invoice`, keeping the Telstra diff clean.

```python
effective_invoice = telstra_invoice + total_adj
# negative adj → reduces invoice by same amount it reduces total_cur
# → telstra_diff stays correct
```

---

## Database Schema (`aws_db.py`)

### `workloads`

Defines all tracked cost centres.

| Column | Type | Notes |
|---|---|---|
| `name` | TEXT PK | Must match `workloads_tag` in CUR (or use `cur_tag` override) |
| `domain` | TEXT | Business domain / team |
| `cost_category` | TEXT | `Shared` / `Consumption` / `Project` / `Other` |
| `budget_manager` | TEXT | Owner name |
| `description` | TEXT | Free text |
| `budget_monthly` | REAL | Monthly budget in AUD |
| `sort_order` | INTEGER | Display order |
| `cur_tag` | TEXT | Override if CUR tag differs from workload name |

### `cur_data`

Raw CUR spend imported from the monthly report file.

| Column | Type | Notes |
|---|---|---|
| `account_id` | TEXT | AWS account ID |
| `account_name` | TEXT | AWS account name |
| `workloads_tag` | TEXT | Tag value from CUR (used to match to workload) |
| `outcomegroup` | TEXT | Secondary grouping tag from CUR |
| `category` | TEXT | `monthly_expense` or `marketplace` |
| `month` | TEXT | ISO date `YYYY-MM-01` |
| `amount` | REAL | Spend in AUD |

Unique key: `(account_id, workloads_tag, category, month)` — re-upload is safe (upsert).

### `monthly_inputs`

Per-month user-entered values.

| Column | Type | Notes |
|---|---|---|
| `month` | TEXT PK | `YYYY-MM-01` |
| `telstra_invoice` | REAL | Actual Telstra invoice amount for that month |
| `forecast_run` | REAL | Monthly run cost forecast target |
| `forecast_project` | REAL | Monthly project X-charge forecast target |

### `marketplace_adjustments`

Per-workload per-month adjustments.

| Column | Type | Notes |
|---|---|---|
| `workload` | TEXT | FK → workloads.name |
| `month` | TEXT | `YYYY-MM-01` |
| `adjustment` | REAL | Negative = paid via PO (removed from Telstra scope) |
| `note` | TEXT | Reason / PO reference |

### `upload_log`

Tracks every CUR file upload.

| Column | Notes |
|---|---|
| `filename` | Original file name |
| `rows_upserted` | Count of DB rows written |
| `months_found` | Count of month columns parsed |
| `uploaded_by` | AD username |
| `uploaded_at` | UTC datetime |

---

## API Routes (`app.py`)

All routes require login. Base path: `/AWSFinOps`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/months` | Available months + last CUR upload timestamp (UTC) |
| GET | `/api/run-cost?month=YYYY-MM-01` | Full compute output for a month (incl. prev month actuals) |
| GET | `/api/summary` | All months rolled up for Summary tab charts |
| GET | `/api/monthly-inputs/<month>` | Get telstra_invoice / forecasts for a month |
| POST | `/api/monthly-inputs/<month>` | Save telstra_invoice / forecasts |
| POST | `/api/upload-cur` | Upload CUR file (multipart/form-data, field: `file`) |
| GET | `/api/upload-history` | Last 20 uploads |
| GET | `/api/workloads` | All workloads |
| POST | `/api/workloads` | Create workload |
| PUT | `/api/workloads/<name>` | Update workload |
| DELETE | `/api/workloads/<name>` | Delete workload (spend rolls into Other) |
| POST | `/api/marketplace-adjustment` | Save/delete adjustment |
| GET | `/api/cur-tags` | All distinct `workloads_tag` values in CUR data |
| POST | `/api/workloads/discover` | Auto-create workloads from unmatched CUR tags |
| GET | `/api/status` | Health check, returns logged-in user |

### SSO Endpoint

`GET /AWSFinOps/sso?user=<username>&ts=<unix_timestamp>&token=<hmac_sha256>`

Allows other internal apps to pass a signed token and auto-login a user without re-entering credentials. Token must be < 60 seconds old. HMAC key = `SSO_SECRET` env var.

---

## CUR File Format (`aws_ingestor.py`)

Accepts `.xlsx`, `.xlsm`, `.xls`, or `.csv`. The file must be a **pivoted monthly report** with this structure:

| Col A | Col B | Col C | Col D | Col E | Col F+ |
|---|---|---|---|---|---|
| `account_id` | `account_name` | `workloads_tag` | `outcomegroup_tag` | `category` | Month columns (`Jan-2025`, `2025-01`, etc.) |

- **Row 1**: Header. Month columns detected automatically from column F onwards.
- **Blank account_id rows**: Skipped (summary/total rows in the export).
- **category**: Must be `monthly_expense` or `marketplace`. Other rows ignored.
- **Re-upload**: Safe — rows are upserted by `(account_id, workloads_tag, category, month)`.

---

## UI Tabs (`index.html`)

### 📊 Detailed Monthly AWS Consumption

- **Financial Year dropdown** + **month pills** (Cochlear FY = July–June, e.g. FY26 = Jul-25 to Jun-26)
- **6 KPI cards** (single row, no wrap): Run Cost | Project Cost | Shared Cost Pool | Marketplace via PO | Grand Total | Telstra Invoice
- **Dev vs Run Forecast banner**: shown only when forecast is set for the selected month
- **Telstra Invoice card subtitle**: shows `telstra_diff_total` as $ and %, coloured red if > 3%, green if ≤ 3%
- **Run Cost table**: one row per Consumption workload + one aggregated "Other" row
- **Project X-charge table**: one row per Project workload
- **Shared Cost table**: one row per Shared workload
- **Month-on-month movement indicators** (▲▼) on each workload row
- **Marketplace adjustment button** per row
- **Inputs bar**: enter Telstra invoice, Run forecast, Project forecast per month
- **Last CUR update** notice (AEST time, computed in browser via `Intl.DateTimeFormat` with `Australia/Sydney`)

### 📈 Summary

- Bar + line charts: Run Cost FinOps vs forecast, Project X-charge FinOps vs forecast
- Tabular month-by-month summary
- Same "last CUR update" notice

### ⚙️ Workloads

- Lists all workloads in four sections: Shared | Run Cost | Project X-charge | Other
- Edit / Delete buttons per row
- "Add workload" button
- CUR tag override field

### 📥 Upload CUR

- Drag-and-drop or click to upload `.xlsx` / `.csv`
- Shows parse result (rows upserted, months found, errors)
- Upload history (last 20)

---

## Seeded Workloads

### Shared (4)
AWS Networks, Billing, Network F5, Network Firewall

### Run Cost / Consumption (12)
Boomi-Integration, Boomi-Gateway, Boomi-Corporate, Bunker Backups, Clinical Cloud, Codacy, Contact Center, DPX MCP, GitLab, MIP, Nautilus, Olingo Odata, Shared Services, Sitecore

### Project X-charge (6)
CNA, Clark AI, DataInsights, MES, Model Gateway, Sonar

### Other — grouped under single "Other" row in Run Cost (25)
Acoustics, AWS Identity, AWS Security, BBTB, Boomi-Data, CCI, CIAM, CRIP, CSP Sandbox, Dexter, Disabled, DNR, Identity, Magento, MRA, Quick Suite, R_D, Rehosted Apps, Rehosted DBs, Sandbox, SFHC Miterra, Sharefile, SimpleMDG, SBOX, Trackwise

---

## Authentication

- Active Directory via **PowerShell + .NET DirectoryServices** (Windows only)
- `AD_GROUP = "Domain Users"` → any domain user can access (no group check)
- `AD_GROUP = "<specific group>"` → only members of that group can access
- Set `AD_ENABLED=false` for local dev / non-Windows environments
- Sessions use Flask signed cookies (`SECRET_KEY`)

---

## Key Business Rules

1. **Shared pool** is distributed to Run + Project workloads proportionally to their actual spend. Shared accounts themselves do not receive a Telstra diff allocation.

2. **Grand Total = Run Cost FinOps + Project X-charge FinOps**. This should equal the Telstra invoice when all CUR tags are matched and the month is complete.

3. **Telstra diff** = `effective_invoice − total_cur`. A large negative diff usually means many CUR `workloads_tag` values are unmatched (accumulating in the "Other" row and inflating `total_cur`). A large positive diff usually means the CUR file is incomplete for that month.

4. **"Other" row** aggregates: (a) the 25 named "Other" category workloads + (b) any truly unmatched CUR tags. Both are included in the allocation denominator (`run_proj_total`).

5. **Marketplace adjustments** with a negative value remove that spend from both the workload's `actual` and the `effective_invoice`, ensuring the Telstra diff remains clean (adjustments don't inflate it).

6. **Financial Year**: Cochlear FY runs July–June. FY26 = Jul-2025 to Jun-2026. The UI groups months by FY in the dropdown using `month >= 6 → year + 1`.

---

## Common Maintenance Tasks

### Add a new workload

1. In the app UI → Workloads tab → Add workload
2. Or add to `_SEED_WORKLOADS` in `aws_db.py` and restart (only adds if not already present)
3. Set `cur_tag` if the CUR `workloads_tag` differs from the workload name

### Change a workload's category

Edit it in the Workloads tab UI, or update the DB directly:
```sql
UPDATE workloads SET cost_category='Project' WHERE name='Model Gateway';
```
Restart is not required — category is read on each page load.

### Update forecasts

Monthly forecasts are seeded for FY27 (Jul-26 to Jun-27) in `aws_db.py → _FY27_FORECASTS`. To add a new FY, append rows there, or enter them manually via the Inputs bar in the UI.

### Upload a new month's CUR data

Upload tab → drag the Excel/CSV file → confirm rows upserted. Re-upload is safe.

### Check what's in the "Other" bucket

Call the API: `GET /AWSFinOps/api/run-cost?month=YYYY-MM-01` and inspect `consumption_rows` where `workload == "Other"` → `unmatched_breakdown` lists any truly unmatched CUR tags with their amounts.

---

## Known Data Issues

- CUR `workloads_tag` values are case-sensitive in the source system but the resolver does a case-insensitive fallback match, so most mismatches are handled automatically (e.g., `Gitlab` → `GitLab`).
- Empty `workloads_tag` (blank) in CUR rows ends up in "Other" as `(blank)`.
- An account with no `workloads_tag` at all contributes to "Other" unmatched spend.

---

## Branch

Active development branch: `claude/web-app-overview-htr1qy`  
Repository: `elvinj-ej/app1`
