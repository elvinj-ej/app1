import os
import sqlite3

DB_PATH = os.environ.get(
    "AWS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_finops.db"),
)

# Workloads as defined in AWS_Run Cost tab rows 17-35 (Consumption) and 39-43 (Project)
_SEED_WORKLOADS = [
    # name, domain, cost_category, budget_manager, description, budget_monthly
    ("AWS Networks",      "ISD",                    "Consumption",       "Andy McLaughlin",          "",                                                              8799.00),
    ("Billing",           "ISD",                    "Consumption",       "Jan Willems",              "Savings plans/Enterprise Support/ISD Marketplace e.g Okta",     21000.00),
    ("Network F5",        "ISD",                    "Consumption",       "Andy McLaughlin",          "",                                                              1340.36),
    ("Network Firewall",  "ISD",                    "Consumption",       "Andy McLaughlin",          "",                                                              1591.24),
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
    # Project X-charge
    ("CNA",               "Corporate Supply Chain", "Project",           "Leigh Wells",              "",                                                              28013.40),
    ("MES",               "Corporate Supply Chain", "Project",           "Rushka Plunkett",          "",                                                              26000.00),
    ("Clark AI",          "ADA",                    "Project",           "Jiten Shah",               "AWG implementations consideration",                             912.60),
    ("DataInsights",      "ADA",                    "Project",           "Jiten Shah",               "AWG implementations consideration",                             2706.40),
    ("Sonar",             "ADA",                    "Project",           "Jiten Shah",               "",                                                              8197.80),
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
            "sort_order     INTEGER DEFAULT 99)"
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

        # Seed workloads (INSERT OR IGNORE keeps existing budget edits)
        for i, (name, domain, cat, mgr, desc, budget) in enumerate(_SEED_WORKLOADS):
            conn.execute(
                "INSERT OR IGNORE INTO workloads "
                "(name, domain, cost_category, budget_manager, description, budget_monthly, sort_order) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, domain, cat, mgr, desc, budget, i),
            )
