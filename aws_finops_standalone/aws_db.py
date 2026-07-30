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
    ("CNA",               "Corporate Supply Chain", "Project",           "Leigh Wells",              "",                                                              28013.40),
    ("MES",               "Corporate Supply Chain", "Project",           "Rushka Plunkett",          "",                                                              26000.00),
    ("Clark AI",          "ADA",                    "Project",           "Jiten Shah",               "AWG implementations consideration",                             round(3000 * 164_000 / 193_200, 2)),
    ("DataInsights",      "ADA",                    "Project",           "Jiten Shah",               "AWG implementations consideration",                             round(3400 * 164_000 / 193_200, 2)),
    ("Sonar",             "ADA",                    "Project",           "Jiten Shah",               "",                                                              round(9700 * 164_000 / 193_200, 2)),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
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
            "workload    TEXT NOT NULL,"
            "month       TEXT NOT NULL,"
            "adjustment  REAL NOT NULL DEFAULT 0,"
            "note        TEXT,"
            "updated_at  DATETIME DEFAULT (datetime('now')),"
            "PRIMARY KEY (workload, month))"
        )

        # Migrate existing Shared Cost accounts from 'Consumption' → 'Shared'
        _SHARED_ACCOUNTS = ("AWS Networks", "Billing", "Network F5", "Network Firewall")
        conn.execute(
            "UPDATE workloads SET cost_category='Shared' WHERE name IN ({}) AND cost_category='Consumption'".format(
                ",".join("?" * len(_SHARED_ACCOUNTS))
            ),
            _SHARED_ACCOUNTS,
        )

        # Migrate workloads that should be 'Other' (grouped line in Run Cost)
        _OTHER_WORKLOADS = (
            "Acoustics", "AWS Identity", "AWS Security", "BBTB", "Boomi-Data",
            "CCI", "CIAM", "CRIP", "CSP Sandbox", "Dexter", "Disabled", "DNR",
            "Identity", "Magento", "MRA", "Quick Suite",
            "R_D", "Rehosted Apps", "Rehosted DBs", "Sandbox", "SFHC Miterra",
            "Sharefile", "SimpleMDG", "SBOX", "Trackwise",
        )
        conn.execute(
            "UPDATE workloads SET cost_category='Other' WHERE name IN ({})".format(
                ",".join("?" * len(_OTHER_WORKLOADS))
            ),
            _OTHER_WORKLOADS,
        )

        # Migrate Model Gateway to Project
        conn.execute("UPDATE workloads SET cost_category='Project' WHERE name='Model Gateway'")

        # Ensure DPX MCP and Olingo Odata remain Consumption
        conn.execute("UPDATE workloads SET cost_category='Consumption' WHERE name IN ('DPX MCP', 'Olingo Odata')")

        # FY27 project annual budgets: MES $560k/yr, CNA $910k+$50k=$960k/yr
        conn.execute("UPDATE workloads SET budget_monthly=? WHERE name='MES'", (560000 / 12,))
        conn.execute("UPDATE workloads SET budget_monthly=? WHERE name='CNA'", (960000 / 12,))

        # ADA group: domain tag + individual FY27 monthly budgets scaled to $164,000/yr annual forecast
        # Ratio = 164,000 / 193,200 (original: Clark AI $3k + DataInsights $3.4k + Sonar $9.7k = $16.1k/mo)
        _ADA_RATIO = 164_000 / 193_200
        conn.execute("UPDATE workloads SET domain='ADA', budget_monthly=? WHERE name='Clark AI'",    (round(3000 * _ADA_RATIO, 2),))
        conn.execute("UPDATE workloads SET domain='ADA', budget_monthly=? WHERE name='DataInsights'", (round(3400 * _ADA_RATIO, 2),))
        conn.execute("UPDATE workloads SET domain='ADA', budget_monthly=? WHERE name='Sonar'",        (round(9700 * _ADA_RATIO, 2),))
        conn.execute("UPDATE workloads SET domain='ADA', budget_monthly=0      WHERE name='Model Gateway'")

        # Schema migrations for existing databases
        existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(workloads)").fetchall()}
        if "domain" not in existing_cols:
            # Old schema used 'outcomegroup' — add domain column and copy data
            conn.execute("ALTER TABLE workloads ADD COLUMN domain TEXT")
            if "outcomegroup" in existing_cols:
                conn.execute("UPDATE workloads SET domain = outcomegroup WHERE domain IS NULL")
        if "cost_category" not in existing_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN cost_category TEXT NOT NULL DEFAULT 'Consumption'")
        if "sort_order" not in existing_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN sort_order INTEGER DEFAULT 99")
        if "cur_tag" not in existing_cols:
            conn.execute("ALTER TABLE workloads ADD COLUMN cur_tag TEXT")

        # monthly_inputs migration: add forecast_run / forecast_project if missing
        mi_cols = {r[1] for r in conn.execute("PRAGMA table_info(monthly_inputs)").fetchall()}
        if "forecast_run" not in mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_run REAL")
        if "forecast_project" not in mi_cols:
            conn.execute("ALTER TABLE monthly_inputs ADD COLUMN forecast_project REAL")

        # Seed FY27 forecasts (INSERT OR IGNORE — user edits via the inputs bar are preserved)
        # Jul–Dec 2026: Run=$305,144  Project=$97,800  (CNA $35.7k, MES $46k, Clark $3k, DataInsights $3.4k, Sonar $9.7k)
        # Jan–Jun 2027: Run=$305,144  Project=$126,100 (CNA increases to $64k)
        _FY27_FORECASTS = [
            ("2026-07-01", 305144, 97800),
            ("2026-08-01", 305144, 97800),
            ("2026-09-01", 305144, 97800),
            ("2026-10-01", 305144, 97800),
            ("2026-11-01", 305144, 97800),
            ("2026-12-01", 305144, 97800),
            ("2027-01-01", 305144, 126100),
            ("2027-02-01", 305144, 126100),
            ("2027-03-01", 305144, 126100),
            ("2027-04-01", 305144, 126100),
            ("2027-05-01", 305144, 126100),
            ("2027-06-01", 305144, 126100),
        ]
        for month, fc_run, fc_proj in _FY27_FORECASTS:
            conn.execute(
                "INSERT OR IGNORE INTO monthly_inputs (month, forecast_run, forecast_project) VALUES (?,?,?)",
                (month, fc_run, fc_proj),
            )

        # Seed workloads (INSERT OR IGNORE keeps existing budget edits)
        for i, (name, domain, cat, mgr, desc, budget) in enumerate(_SEED_WORKLOADS):
            conn.execute(
                "INSERT OR IGNORE INTO workloads "
                "(name, domain, cost_category, budget_manager, description, budget_monthly, sort_order) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, domain, cat, mgr, desc, budget, i),
            )
