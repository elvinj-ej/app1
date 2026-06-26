"""
aws_run_cost.py — Core aggregation engine.

For a given month:
  1. Sum monthly_expense per workloads_tag from CUR.
  2. Named workloads (in the workloads table) each get their own row.
  3. Other = total CUR monthly_expense − sum of all named workload actuals.
  4. Telstra Diff = (telstra_invoice − total_cur) × (row_actual / total_cur).
  5. Total = Actual + Telstra Diff.
  6. Deviation = Total − budget_monthly (per workload) or vs forecast (totals).

All amounts in USD.
"""

from __future__ import annotations
import logging
from typing import Any
from aws_db import get_conn

log = logging.getLogger(__name__)


def get_available_months() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT month FROM cur_data WHERE category='monthly_expense' ORDER BY month"
        ).fetchall()
    return [r["month"] for r in rows]


def get_workloads() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, domain, department, budget_manager, description, budget_monthly "
            "FROM workloads ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_monthly_input(month: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT telstra_invoice, forecast FROM monthly_inputs WHERE month=?", (month,)
        ).fetchone()
    return dict(row) if row else {"telstra_invoice": None, "forecast": None}


def compute_run_cost(month: str) -> dict[str, Any]:
    with get_conn() as conn:
        cur_rows = conn.execute("""
            SELECT COALESCE(workloads_tag,'__untagged__') AS tag, SUM(amount) AS actual
            FROM cur_data
            WHERE month=? AND category='monthly_expense'
            GROUP BY workloads_tag
        """, (month,)).fetchall()

        workloads = conn.execute(
            "SELECT name, domain, department, budget_manager, budget_monthly "
            "FROM workloads ORDER BY name"
        ).fetchall()

        monthly = conn.execute(
            "SELECT telstra_invoice, forecast FROM monthly_inputs WHERE month=?", (month,)
        ).fetchone()

    tag_actual: dict[str, float] = {r["tag"]: (r["actual"] or 0) for r in cur_rows}
    total_cur = sum(tag_actual.values())

    named = {w["name"] for w in workloads}

    # Map CUR tags → canonical workload name (case-insensitive fallback)
    tag_map: dict[str, float] = {}
    for tag, actual in tag_actual.items():
        if tag in named:
            key = tag
        else:
            key = next((n for n in named if n.lower() == tag.lower()), None)
        if key:
            tag_map[key] = tag_map.get(key, 0) + actual
        # else → Other

    named_total  = sum(tag_map.values())
    other_actual = max(0.0, total_cur - named_total)

    telstra_invoice = float((monthly["telstra_invoice"] if monthly else None) or 0)
    forecast        = (monthly["forecast"] if monthly else None)

    diff_total = telstra_invoice - total_cur if telstra_invoice else 0.0

    def _t_share(row_actual: float) -> float:
        if total_cur == 0 or not telstra_invoice:
            return 0.0
        return diff_total * (row_actual / total_cur)

    rows = []
    for w in workloads:
        actual = tag_map.get(w["name"], 0.0)
        t_diff = _t_share(actual)
        total  = actual + t_diff
        budget = float(w["budget_monthly"] or 0)
        rows.append({
            "workload":           w["name"],
            "domain":             w["domain"] or "",
            "department":         w["department"] or "",
            "budget_manager":     w["budget_manager"] or "",
            "budget_monthly":     budget or None,
            "actual":             actual,
            "telstra_diff":       t_diff,
            "total":              total,
            "deviation_to_budget": (total - budget) if budget else None,
        })

    other_tdiff = _t_share(other_actual)
    rows.append({
        "workload":           "Other",
        "domain":             "ALL",
        "department":         "",
        "budget_manager":     "",
        "budget_monthly":     None,
        "actual":             other_actual,
        "telstra_diff":       other_tdiff,
        "total":              other_actual + other_tdiff,
        "deviation_to_budget": None,
    })

    total_finops = sum(r["total"] for r in rows)
    deviation_fc = (total_finops - forecast) if forecast else None

    return {
        "month":                 month,
        "telstra_invoice":       telstra_invoice,
        "forecast":              forecast,
        "total_cur_actual":      total_cur,
        "total_telstra_diff":    diff_total,
        "total_finops":          total_finops,
        "deviation_to_forecast": deviation_fc,
        "rows":                  rows,
    }
