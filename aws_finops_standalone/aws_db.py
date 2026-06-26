import os
import sqlite3

DB_PATH = os.environ.get(
    "AWS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_finops.db"),
)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cur_data ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "account_id TEXT NOT NULL,"
            "account_name TEXT,"
            "workloads_tag TEXT NOT NULL DEFAULT '',"
            "outcomegroup TEXT,"
            "category TEXT NOT NULL,"
            "month TEXT NOT NULL,"
            "amount REAL NOT NULL DEFAULT 0,"
            "UNIQUE(account_id, workloads_tag, category, month))"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cur_month ON cur_data(month)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cur_workload ON cur_data(workloads_tag)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cur_category ON cur_data(category)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS workloads ("
            "name TEXT PRIMARY KEY,"
            "outcomegroup TEXT,"
            "department TEXT,"
            "budget_manager TEXT,"
            "description TEXT,"
            "budget_monthly REAL DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS monthly_inputs ("
            "month TEXT PRIMARY KEY,"
            "telstra_invoice REAL,"
            "forecast REAL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS upload_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "filename TEXT,"
            "rows_upserted INTEGER,"
            "months_found INTEGER,"
            "uploaded_by TEXT,"
            "uploaded_at DATETIME DEFAULT (datetime('now')))"
        )
