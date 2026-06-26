"""
aws_db.py
---------
SQLite database initialisation for the AWS FinOps tracker.

DB file location: next to this script, named aws_finops.db
Override with environment variable AWS_DB_PATH.
"""

import os
import sqlite3

DB_PATH = os.environ.get(
    "AWS_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_finops.db"),
)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist yet. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript("""
        -- Raw CUR data (one row per account+workload+category+month)
        CREATE TABLE IF NOT EXISTS cur_data (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id    TEXT    NOT NULL,
            account_name  TEXT,
            workloads_tag TEXT,
            outcomegroup  TEXT,
            category      TEXT    NOT NULL,   -- 'monthly_expense' | 'marketplace'
            month         TEXT    NOT NULL,   -- 'YYYY-MM-01'
            amount        REAL    NOT NULL DEFAULT 0,
            UNIQUE(account_id, COALESCE(workloads_tag,''), category, month)
            ON CONFLICT REPLACE
        );

        CREATE INDEX IF NOT EXISTS idx_cur_month     ON cur_data(month);
        CREATE INDEX IF NOT EXISTS idx_cur_workload  ON cur_data(workloads_tag);
        CREATE INDEX IF NOT EXISTS idx_cur_category  ON cur_data(category);

        -- Named workloads (mirrors the Exclusion tab + AWS_Run Cost metadata)
        CREATE TABLE IF NOT EXISTS workloads (
            name           TEXT PRIMARY KEY,
            domain         TEXT,
            department     TEXT,
            budget_manager TEXT,
            description    TEXT,
            budget_monthly REAL DEFAULT 0
        );

        -- Monthly manual inputs: Telstra invoice total + Latest F/C per month
        CREATE TABLE IF NOT EXISTS monthly_inputs (
            month           TEXT PRIMARY KEY,   -- 'YYYY-MM-01'
            telstra_invoice REAL,
            forecast        REAL
        );

        -- Upload history log
        CREATE TABLE IF NOT EXISTS upload_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT,
            rows_upserted INTEGER,
            months_found  INTEGER,
            uploaded_by  TEXT,
            uploaded_at  DATETIME DEFAULT (datetime('now'))
        );
        """)
