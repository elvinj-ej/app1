"""
Agent memory — persisted as key/value rows in SQLite (agent_memory table).
Values are JSON-encoded so lists, dicts, and numbers all round-trip cleanly.
"""
import json
import sqlite3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from aws_db import get_conn


def _ensure_table():
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_memory ("
            "key        TEXT PRIMARY KEY,"
            "value      TEXT NOT NULL,"
            "updated_at DATETIME DEFAULT (datetime('now')))"
        )


def read(key: str, default=None):
    _ensure_table()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM agent_memory WHERE key=?", (key,)
        ).fetchone()
    if row is None:
        return default
    return json.loads(row[0])


def write(key: str, value) -> None:
    _ensure_table()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_memory (key, value, updated_at) VALUES (?,?,datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value)),
        )


def read_all() -> dict:
    _ensure_table()
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM agent_memory").fetchall()
    return {r[0]: json.loads(r[1]) for r in rows}
