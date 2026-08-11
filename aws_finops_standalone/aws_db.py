import os
import sqlite3

DB_PATH = os.environ.get(
    "AWS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_finops.db"),
)

# Workloads as defined in AWS_Run Cost tab rows 17-35 (Consumption) and 39-43 (Project)
_SEED_WORKLOADS = [
    # name, domain, cost_category, budget_manager, description, budget_monthly
    ("AWS Networks",      "ISD",                    "Shared",            "Andy McLaughlin",          "",                                                              8799.00),
    ("Billing",           "ISD",                    "Shared",            "Jan Willems",              "Savings plans/Enterprise Support/ISD Marketplace e.g Okta",     21000.00),
    ("Network F5",        "ISD",                    "Shared",            "Andy McLaughlin",          "",                                                              1340.36),
    ("Network Firewall",  "ISD",                    "Shared",            "Andy McLaughlin",          "",                                                              1591.24),
    ("Boomi-Integration", "Digital Technology",     "Consumption",       "Joseph Encomienda",        "",                                                              12783.20),
    ("Boomi-Gateway",     "Digital Technology",     "Consumption",       "Joseph Encomienda",        "",                                                              5022.80),
    ("Bunker Backups",    "ISD",                    "Consumption",       "Jan Willems",              "",                                                              24295.60),
    ("Clinical Cloud",    "Corporate Supply Chain", "Consumption",       "Sam Jarman",               "",                                                              99995.00),
    ("Codacy",            "Digital Technology",     "Consumption",       "Dinesh Selvam",            "Non-Prod - shutdown in Jan26. Flat for prod",                   2854.20),
    ("Contact Center",    "Commercial Operations",  "Consumption",       "Andy McLaughlin",          "",                                                              38902.03),
    ("DPX MCP",           "Corporate Supply Chain", "Consumption",       "Cherry Zhang",             "Growth in some accounts - agentic workloads",                   6740.80),
    ("Sitecore",          "Commercial Operations",  "Consumption",       "Dinesh Selvam",            "",                                                              13350.54),
    ("MIP",               "Corporate Supply Chain", "Consumption",       "Rob Pearson",              "",                                                              6513.80),
    ("Olingo Odata",      "Corporate Supply Chain", "Consumption",       "Cherry Zhang",             "",                                                              3797.20),
    ("Nautilus",          "Corporate Supply Chain", "Consumption",       "Roger Calixto",            "",                                                              3342.80),
    ("GitLab",            "Digital Technology",     "Consumption",       "Sam Jarman",               "",                                                              1352.60),
    ("Shared Services",   "ISD",                    "Consumption",       "Ignus Swart/Jan Willems",  "",                                                              15900.40),
    ("Boomi-Corporate",   "Corporate Supply Chain", "Consumption",       "Joseph Encomienda",        "",                                                              1848.20),
    # Other tracked workloads — matched from CUR but grouped as one "Other" row in Run Cost
    ("Acoustics",         "",                       "Other",             "",                         "",                                                              0),
    ("AWS Identity",      "",                       "Other",             "",                         "",                                                              0),
    ("AWS Security",      "",                       "Other",             "",                         "",                                                              0),
    ("BBTB",              "",                       "Other",             "",                         "",                                                              0),
    ("Boomi-Data",        "",                       "Other",             "",                         "",                                                              0),
    ("CCI",               "",                       "Other",             "",                         "",                                                              0),
    ("CIAM",              "",                       "Other",             "",                         "",                                                              0),
    ("CRIP",              "",                       "Other",             "",                         "",                                                              0),
    ("CSP Sandbox",       "",                       "Other",             "",                         "",                                                              0),
    ("Dexter",            "",                       "Other",             "",                         "",                                                              0),
    ("Disabled",          "",                       "Other",             "",                         "",                                                              0),
    ("DNR",               "",                       "Other",             "",                         "",                                                              0),
    ("DPX MCP",           "Corporate Supply Chain", "Consumption",       "Cherry Zhang",             "Growth in some accounts - agentic workloads",                   6740.80),
    ("Identity",          "",                       "Other",             "",                         "",                                                              0),
    ("Magento",           "",                       "Other",             "",                         "",                                                              0),
    ("MRA",               "",                       "Other",             "",                         "",                                                              0),
    ("Olingo Odata",      "Corporate Supply Chain", "Consumption",       "Cherry Zhang",             "",                                                              3797.20),
    ("Quick Suite",       "",                       "Other",             "",                         "",                                                              0),
    ("R_D",               "",                       "Other",             "",                         "",                                                              0),
    ("Rehosted Apps",     "",                       "Other",             "",                         "",                                                              0),
    ("Rehosted DBs",      "",                       "Other",             "",                         "",                                                              0),
    ("Sandbox",           "",                       "Other",             "",                         "",                                                              0),
    ("SFHC Miterra",      "",                       "Other",             "",                         "",                                                              0),
    ("Sharefile",         "",                       "Other",             "",                         "",                                                              0),
    ("SimpleMDG",         "",                       "Other",             "",                         "",                                                              0),
    ("SBOX",              "",                       "Other",             "",                         "",                                                              0),
    ("Trackwise",         "",                       "Other",             "",                         "",                                                              0),
    # Project X-charge
    ("Model Gateway",     "",                       "Project",           "",                         "",                                                              0),
    ("CNA",               "Corporate Supply Chain", "Project",           "Leigh Wells",              "Jul-Dec $35,700/mo · Jan-Jun $64,000/mo",                       35700.00),
    ("MES",               "Corporate Supply Chain", "Project",           "Rushka Plunkett",          "",                                                              round(560000/12, 2)),
    ("Clark AI",          "ADA",                    "Project",           "Jennifer Ilaya",           "AWG implementations consideration",                             0),
    ("DataInsights",      "ADA",                    "Project",           "Jennifer Ilaya",           "AWG implementations consideration",                             0),
    ("Sonar",             "ADA",                    "Project",           "Jennifer Ilaya",           "",                                                              0),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        # ── Core tables (always idempotent) ───────────────────────────────────
        conn.execute(
            "CREATE TABLE IF NOT EXISTS workloads ("
            "name           TEXT PRIMARY KEY,"
            "domain         TEXT,"
            "cost_category  TEXT NOT NULL DEFAULT 'Consumption',"
            "budget_manager TEXT,"
            "description    TEXT,"
            "budget_monthly REAL DEFAULT 0,"
            "sort_order     INTEGER DEFAULT 99,"
            "cur_tag        TEXT)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cur_data ("
            "id            INTEGER PRIMARY KEY AUTOINCREMENT,"
            "account_id    TEXT NOT NULL,"
            "account_name  TEXT,"
            "workloads_tag TEXT NOT NULL DEFAULT '',"
            "outcomegroup  TEXT,"
            "category      TEXT NOT NULL,"
            "month         TEXT NOT NULL,"
            "amount        REAL NOT NULL DEFAULT 0,"
            "UNIQUE(account_id, workloads_tag, category, month))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cur_month    ON cur_data(month)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cur_workload ON cur_data(workloads_tag)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cur_category ON cur_data(category)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS monthly_inputs ("
            "month            TEXT PRIMARY KEY,"
            "telstra_invoice  REAL,"
            "forecast_run     REAL,"
            "forecast_project REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS upload_log ("
            "id            INTEGER PRIMARY KEY AUTOINCREMENT,"
            "filename      TEXT,"
            "rows_upserted INTEGER,"
            "months_found  INTEGER,"
            "uploaded_by   TEXT,"
            "uploaded_at   DATETIME DEFAULT (datetime('now')))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS marketplace_adjustments ("
            "workload        TEXT NOT NULL,"
            "month           TEXT NOT NULL,"
            "adjustment      REAL NOT NULL DEFAULT 0,"
            "note            TEXT,"
            "po_number       TEXT,"
            "purchaser_name  TEXT,"
            "updated_at      DATETIME DEFAULT (datetime('now')),"
            "PRIMARY KEY (workload, month))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS receiving_forecast ("
            "month              TEXT PRIMARY KEY,"
            "received_forecast  REAL,"
            "forecast_note      TEXT,"
            "updated_at         DATETIME DEFAULT (datetime('now')))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS invoice_uploads ("
            "id              INTEGER PRIMARY KEY AUTOINCREMENT,"
            "month           TEXT NOT NULL,"
            "filename        TEXT NOT NULL,"
            "pdf_blob        BLOB,"
            "account_number  TEXT,"
            "validated       INTEGER DEFAULT 0,"
            "total_new_charges REAL,"
            "uploaded_by     TEXT,"
            "uploaded_at     DATETIME DEFAULT (datetime('now')))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS invoice_line_items ("
            "id              INTEGER PRIMARY KEY AUTOINCREMENT,"
            "invoice_id      INTEGER NOT NULL REFERENCES invoice_uploads(id),"
            "month           TEXT NOT NULL,"
            "line_type       TEXT,"
            "description     TEXT,"
            "amount          REAL,"
            "po_number       TEXT,"
            "workload_match  TEXT)"
        )
        # Snapshot table — saves "before" state for every row touched by an upload
        # so uploads can be individually reverted.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cur_data_snapshots ("
            "upload_id     INTEGER NOT NULL,"
            "account_id    TEXT NOT NULL,"
            "workloads_tag TEXT NOT NULL DEFAULT '',"
            "category      TEXT NOT NULL,"
            "month         TEXT NOT NULL,"
            "account_name  TEXT,"
            "outcomegroup  TEXT,"
            "old_amount    REAL,"   # NULL = row was newly inserted (didn't exist before)
            "PRIMARY KEY (upload_id, account_id, workloads_tag, category, month))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_upload ON cur_data_snapshots(upload_id)")

        # Migrations registry — every data-change migration is recorded here and
        # runs exactly once, so restarts never overwrite user-saved values.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "id         TEXT PRIMARY KEY,"
            "applied_at DATETIME DEFAULT (datetime('now')))"
        )

        # ── Column additions (gated on absence — safe to repeat) ─────────────
        _wl_cols = {r[1] for r in conn.execute("PRAGMA table_info(workloads)").fetchall()}
        if "domain" not in _wl_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN domain TEXT")
            if "outcomegroup" in _wl_cols:
                conn.execute("UPDATE workloads SET domain = outcomegroup WHERE domain IS NULL")
        if "cost_category" not in _wl_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN cost_category TEXT NOT NULL DEFAULT 'Consumption'")
        if "sort_order" not in _wl_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN sort_order INTEGER DEFAULT 99")
        if "cur_tag" not in _wl_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN cur_tag TEXT")

        _ma_cols = {r[1] for r in conn.execute("PRAGMA table_info(marketplace_adjustments)").fetchall()}
        if "po_number" not in _ma_cols:
            conn.execute("ALTER TABLE marketplace_adjustments ADD COLUMN po_number TEXT")
        if "purchaser_name" not in _ma_cols:
            conn.execute("ALTER TABLE marketplace_adjustments ADD COLUMN purchaser_name TEXT")

        _mi_cols = {r[1] for r in conn.execute("PRAGMA table_info(monthly_inputs)").fetchall()}
        if "forecast_run" not in _mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_run REAL")
        if "forecast_project" not in _mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_project REAL")
        if "forecast_ada" not in _mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_ada REAL")
        if "forecast_mes" not in _mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_mes REAL")
        if "forecast_cna" not in _mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_cna REAL")

        # ── Helper: run a migration exactly once ──────────────────────────────
        def _done(mid):
            return conn.execute("SELECT 1 FROM _migrations WHERE id=?", (mid,)).fetchone() is not None

        def _mark(mid):
            conn.execute("INSERT OR IGNORE INTO _migrations (id) VALUES (?)", (mid,))

        # ── One-time data migrations ──────────────────────────────────────────

        if not _done("m01_shared_cost_category"):
            _SHARED = ("AWS Networks", "Billing", "Network F5", "Network Firewall")
            conn.execute(
                "UPDATE workloads SET cost_category='Shared' WHERE name IN ({}) AND cost_category='Consumption'".format(
                    ",".join("?" * len(_SHARED))), _SHARED)
            _mark("m01_shared_cost_category")

        if not _done("m02_other_cost_category"):
            _OTHER = (
                "Acoustics", "AWS Identity", "AWS Security", "BBTB", "Boomi-Data",
                "CCI", "CIAM", "CRIP", "CSP Sandbox", "Dexter", "Disabled", "DNR",
                "Identity", "Magento", "MRA", "Quick Suite",
                "R_D", "Rehosted Apps", "Rehosted DBs", "Sandbox", "SFHC Miterra",
                "Sharefile", "SimpleMDG", "SBOX", "Trackwise",
            )
            conn.execute(
                "UPDATE workloads SET cost_category='Other' WHERE name IN ({})".format(
                    ",".join("?" * len(_OTHER))), _OTHER)
            _mark("m02_other_cost_category")

        if not _done("m03_model_gateway_project"):
            conn.execute("UPDATE workloads SET cost_category='Project' WHERE name='Model Gateway'")
            _mark("m03_model_gateway_project")

        if not _done("m04_dpx_olingo_consumption"):
            conn.execute("UPDATE workloads SET cost_category='Consumption' WHERE name IN ('DPX MCP', 'Olingo Odata')")
            _mark("m04_dpx_olingo_consumption")

        if not _done("m05_mes_budget_fy27"):
            conn.execute("UPDATE workloads SET budget_monthly=? WHERE name='MES'", (round(560000 / 12, 2),))
            _mark("m05_mes_budget_fy27")

        if not _done("m06_cna_budget_fy27"):
            # Jul–Dec 2026 = $35,700/mo · Jan–Jun 2027 = $64,000/mo
            # Store the lower period value; email endpoint selects the right amount per month.
            conn.execute("UPDATE workloads SET budget_monthly=35700.0 WHERE name='CNA'")
            _mark("m06_cna_budget_fy27")

        if not _done("m07_ada_domain_manager"):
            for _n in ("Clark AI", "DataInsights", "Sonar", "Model Gateway"):
                conn.execute(
                    "UPDATE workloads SET domain='ADA', budget_manager='Jennifer Ilaya', budget_monthly=0 WHERE name=?",
                    (_n,),
                )
            _mark("m07_ada_domain_manager")

        if not _done("m08_forecast_ada_fy27"):
            # ADA group forecast = USD 244,000 / 12 ≈ 20,333/mo for all FY27 months
            _ADA_MONTHLY = round(244_000 / 12, 2)
            for _m in [
                "2026-07-01","2026-08-01","2026-09-01","2026-10-01","2026-11-01","2026-12-01",
                "2027-01-01","2027-02-01","2027-03-01","2027-04-01","2027-05-01","2027-06-01",
            ]:
                conn.execute(
                    "INSERT INTO monthly_inputs (month, forecast_ada) VALUES (?,?) "
                    "ON CONFLICT(month) DO UPDATE SET forecast_ada=COALESCE(forecast_ada, excluded.forecast_ada)",
                    (_m, _ADA_MONTHLY),
                )
            _mark("m08_forecast_ada_fy27")

        if not _done("m09_forecast_project_mes_cna_fy27"):
            # forecast_project now covers MES+CNA only (ADA split out to forecast_ada).
            # Update any month still holding the old combined value of 97800 to 82367.
            for _m in [
                "2026-07-01","2026-08-01","2026-09-01","2026-10-01","2026-11-01","2026-12-01",
                "2027-01-01","2027-02-01","2027-03-01","2027-04-01","2027-05-01","2027-06-01",
            ]:
                conn.execute(
                    "UPDATE monthly_inputs SET forecast_project=82367 WHERE month=? AND forecast_project=97800",
                    (_m,),
                )
            _mark("m09_forecast_project_mes_cna_fy27")

        if not _done("m10_forecast_project_cna_increase_jan27"):
            # CNA budget increases from $35,700/mo to $64,000/mo from Jan 2027.
            # Jan-Jun 2027 forecast_project = 82,367 (MES+CNA base) + 28,300 (CNA increase) = 110,667.
            # Update any month still holding the old combined value of 126100.
            for _m in [
                "2027-01-01","2027-02-01","2027-03-01","2027-04-01","2027-05-01","2027-06-01",
            ]:
                conn.execute(
                    "UPDATE monthly_inputs SET forecast_project=110667 WHERE month=? AND forecast_project=126100",
                    (_m,),
                )
            _mark("m10_forecast_project_cna_increase_jan27")

        if not _done("m11_forecast_mes_cna_fy27"):
            # Seed per-workload forecasts now that MES and CNA are tracked independently.
            # MES: $46,667/mo all year. CNA: $35,700 Jul-Dec 2026, $64,000 Jan-Jun 2027.
            _MES = round(560_000 / 12, 2)
            _FC_MES_CNA = [
                ("2026-07-01", _MES, 35700.0),
                ("2026-08-01", _MES, 35700.0),
                ("2026-09-01", _MES, 35700.0),
                ("2026-10-01", _MES, 35700.0),
                ("2026-11-01", _MES, 35700.0),
                ("2026-12-01", _MES, 35700.0),
                ("2027-01-01", _MES, 64000.0),
                ("2027-02-01", _MES, 64000.0),
                ("2027-03-01", _MES, 64000.0),
                ("2027-04-01", _MES, 64000.0),
                ("2027-05-01", _MES, 64000.0),
                ("2027-06-01", _MES, 64000.0),
            ]
            for _m, _fmes, _fcna in _FC_MES_CNA:
                conn.execute(
                    "INSERT INTO monthly_inputs (month, forecast_mes, forecast_cna) VALUES (?,?,?) "
                    "ON CONFLICT(month) DO UPDATE SET "
                    "forecast_mes=COALESCE(forecast_mes, excluded.forecast_mes), "
                    "forecast_cna=COALESCE(forecast_cna, excluded.forecast_cna)",
                    (_m, _fmes, _fcna),
                )
            _mark("m11_forecast_mes_cna_fy27")

        # ── Seed data (INSERT OR IGNORE — never overwrites existing rows) ─────

        # FY27 forecasts (forecast_project kept for backward compat but superseded by mes+cna)
        _FY27_FORECASTS = [
            ("2026-07-01", 305144,  82367, round(560_000/12, 2), 35700.0),
            ("2026-08-01", 305144,  82367, round(560_000/12, 2), 35700.0),
            ("2026-09-01", 305144,  82367, round(560_000/12, 2), 35700.0),
            ("2026-10-01", 305144,  82367, round(560_000/12, 2), 35700.0),
            ("2026-11-01", 305144,  82367, round(560_000/12, 2), 35700.0),
            ("2026-12-01", 305144,  82367, round(560_000/12, 2), 35700.0),
            ("2027-01-01", 305144, 110667, round(560_000/12, 2), 64000.0),
            ("2027-02-01", 305144, 110667, round(560_000/12, 2), 64000.0),
            ("2027-03-01", 305144, 110667, round(560_000/12, 2), 64000.0),
            ("2027-04-01", 305144, 110667, round(560_000/12, 2), 64000.0),
            ("2027-05-01", 305144, 110667, round(560_000/12, 2), 64000.0),
            ("2027-06-01", 305144, 110667, round(560_000/12, 2), 64000.0),
        ]
        for month, fc_run, fc_proj, fc_mes, fc_cna in _FY27_FORECASTS:
            conn.execute(
                "INSERT OR IGNORE INTO monthly_inputs "
                "(month, forecast_run, forecast_project, forecast_mes, forecast_cna) VALUES (?,?,?,?,?)",
                (month, fc_run, fc_proj, fc_mes, fc_cna),
            )

        # Workloads
        for i, (name, domain, cat, mgr, desc, budget) in enumerate(_SEED_WORKLOADS):
            conn.execute(
                "INSERT OR IGNORE INTO workloads "
                "(name, domain, cost_category, budget_manager, description, budget_monthly, sort_order) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, domain, cat, mgr, desc, budget, i),
            )
