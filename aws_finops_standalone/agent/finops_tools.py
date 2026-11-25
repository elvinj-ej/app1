"""
Claude tool definitions + implementations for the FinOps agent.
Each function is called by the agent when Claude decides to use a tool.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from aws_run_cost import get_available_months, compute
from aws_db import get_conn
import memory as _mem

# ── Tool schemas (passed to Claude API) ───────────────────────────────────────

TOOLS = [
    {
        "name": "get_available_months",
        "description": "Return the list of months that have CUR data in the database, as YYYY-MM-DD strings.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_workload_data",
        "description": (
            "Return full computed FinOps data for a given month. "
            "Includes per-workload actuals, budgets, shared alloc, deviations, and totals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "Month in YYYY-MM-DD format, e.g. 2026-11-01"}
            },
            "required": ["month"],
        },
    },
    {
        "name": "get_account_level_spend",
        "description": "Return per-account spend for a workload tag in a given month, ranked by amount.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month":        {"type": "string", "description": "Month in YYYY-MM-DD format"},
                "workload_tag": {"type": "string", "description": "Workload tag name, e.g. 'MES', 'CNA'"},
            },
            "required": ["month", "workload_tag"],
        },
    },
    {
        "name": "read_memory",
        "description": "Read a value from agent memory by key. Returns null if not found.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Memory key to read"}
            },
            "required": ["key"],
        },
    },
    {
        "name": "write_memory",
        "description": "Persist a value to agent memory so it is available on future runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "Memory key"},
                "value": {"description": "Any JSON-serialisable value to store"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "get_ytd_trend",
        "description": (
            "Return month-by-month actuals for a workload across all available months "
            "so the agent can identify trends."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "workload_name": {"type": "string", "description": "Workload name, e.g. 'MES', 'CNA', 'ADA'"}
            },
            "required": ["workload_name"],
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────────

def _run_get_available_months(_input: dict) -> str:
    months = get_available_months()
    return json.dumps(months)


def _run_get_workload_data(inp: dict) -> str:
    month = inp["month"]
    data = compute(month)
    # Serialise — convert any non-serialisable types
    def _safe(v):
        if isinstance(v, float):
            return round(v, 2)
        return v
    result = {k: _safe(v) if not isinstance(v, (list, dict)) else v
              for k, v in data.items()}
    return json.dumps(result, default=str)


def _run_get_account_level_spend(inp: dict) -> str:
    month        = inp["month"]
    workload_tag = inp["workload_tag"]
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT account_id, account_name, SUM(amount) AS total "
            "FROM cur_data "
            "WHERE month=? AND workloads_tag=? "
            "GROUP BY account_id, account_name "
            "ORDER BY total DESC",
            (month, workload_tag),
        ).fetchall()
    result = [
        {"account_id": r["account_id"], "account_name": r["account_name"] or "", "total": round(r["total"], 2)}
        for r in rows
    ]
    return json.dumps(result)


def _run_read_memory(inp: dict) -> str:
    value = _mem.read(inp["key"])
    return json.dumps(value)


def _run_write_memory(inp: dict) -> str:
    _mem.write(inp["key"], inp["value"])
    return json.dumps({"ok": True})


def _run_get_ytd_trend(inp: dict) -> str:
    workload_name = inp["workload_name"]
    months = get_available_months()
    trend = []
    for m in months:
        data = compute(m)
        # Search consumption_rows, project_rows, ada_rows
        for section in ("consumption_rows", "project_rows", "ada_rows", "shared_rows"):
            for row in data.get(section, []):
                if row.get("workload", "").upper() == workload_name.upper():
                    trend.append({
                        "month":   m,
                        "actual":  round(row.get("actual", 0), 2),
                        "budget":  round(row.get("budget", 0), 2),
                        "total":   round(row.get("total", row.get("actual", 0)), 2),
                    })
                    break
    return json.dumps(trend)


# ── Dispatcher ────────────────────────────────────────────────────────────────

_DISPATCH = {
    "get_available_months":   _run_get_available_months,
    "get_workload_data":      _run_get_workload_data,
    "get_account_level_spend": _run_get_account_level_spend,
    "read_memory":            _run_read_memory,
    "write_memory":           _run_write_memory,
    "get_ytd_trend":          _run_get_ytd_trend,
}


def run_tool(name: str, tool_input: dict) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return fn(tool_input)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
