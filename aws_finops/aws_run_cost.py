"""
aws_run_cost.py
---------------
Core aggregation engine — reproduces the AWS_Run Cost tab logic in Python.

For a given month:
  1. Sum monthly_expense per workloads_tag from CUR data.
  2. Named workloads (in the workloads table) each get their own row.
  3. "Other" = total CUR monthly_expense − sum of all named workload actuals.
  4. Telstra Diff = (telstra_invoice − total_cur) distributed proportionally
     across each row by its share of total CUR spend.
  5. Total = Actual + Telstra Diff.
  6. Deviation = Total − Forecast (if forecast is set for that workload/month).

All amounts in USD.
"""

from __future__ import annotations
import logging
from typing import Any
from aws_db import get_conn

log = logging.getLogger(__name__)


def _fmt(val: float | None) -> str:
    """Format a USD number with commas, no decimals. Empty string for zero/None."""
    if val is None:
        return ""
    rounded = round(val)
    if rounded == 0:
        return ""
    return f"{rounded:,}"


def get_available_months() -> list[str]:
    """Return all months that have CUR data, sorted ascending."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT month FROM cur_data
            WHERE category = 'monthly_expense'
            ORDER BY month
        """).fetchall()
    return [r["month"] for r in rows]


def get_workloads() -> list[dict]:
    """Return all named workloads ordered by name."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, domain, department, budget_manager, description, budget_monthly "
            "FROM workloads ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_monthly_input(month: str) -> dict:
    """Return the manual inputs for a given month (telstra_invoice, forecast)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT telstra_invoice, forecast FROM monthly_inputs WHERE month = ?", (month,)
        ).fetchone()
    return dict(row) if row else {"telstra_invoice": None, "forecast": None}


def compute_run_cost(month: str) -> dict[str, Any]:
    """
    Compute the full run-cost breakdown for a single month.

    Returns:
    {
      month, telstra_invoice, forecast,
      total_cur_actual,
      total_telstra_diff,
      total_finops,
      deviation_to_forecast,
      rows: [
        { workload, domain, department, budget_manager, budget_monthly,
          actual, telstra_diff, total, deviation_to_budget },
        ...
        { workload: 'Other', ... }   ← last row
      ]
    }
    """
    with get_conn() as conn:
        # Per-workload actuals from CUR (monthly_expense only)
        cur_rows = conn.execute("""
            SELECT COALESCE(workloads_tag, '__untagged__') AS tag,
                   SUM(amount) AS actual
            FROM cur_data
            WHERE month = ? AND category = 'monthly_expense'
            GROUP BY workloads_tag
        """, (month,)).fetchall()

        workloads = conn.execute(
            "SELECT name, domain, department, budget_manager, budget_monthly "
            "FROM workloads ORDER BY name"
        ).fetchall()

        monthly = conn.execute(
            "SELECT telstra_invoice, forecast FROM monthly_inputs WHERE month = ?", (month,)
        ).fetchone()

    # Build a lookup: tag → actual
    tag_actual: dict[str, float] = {r["tag"]: (r["actual"] or 0) for r in cur_rows}
    total_cur = sum(tag_actual.values())

    # Named workloads set (for "Other" calculation)
    named = {w["name"] for w in workloads}
    # Sum of actuals for all named workloads (using case-insensitive match)
    tag_map: dict[str, float] = {}
    for tag, actual in tag_actual.items():
        # Try exact match first, then case-insensitive
        if tag in named:
            tag_map[tag] = tag_map.get(tag, 0) + actual
        else:
            matched = next((n for n in named if n.lower() == tag.lower()), None)
            if matched:
                tag_map[matched] = tag_map.get(matched, 0) + actual
            # else: falls into Other

    named_total = sum(tag_map.values())
    other_actual = max(0.0, total_cur - named_total)

    telstra_invoice = (monthly["telstra_invoice"] if monthly else None) or 0.0
    forecast        = (monthly["forecast"]        if monthly else None)

    # Telstra diff = difference between what Telstra invoiced and raw CUR total
    # Distributed proportionally by each row's share of total CUR spend
    telstra_diff_total = telstra_invoice - total_cur if telstra_invoice else 0.0

    def _telstra_share(row_actual: float) -> float:
        if total_cur == 0 or telstra_invoice == 0:
            return 0.0
        return telstra_diff_total * (row_actual / total_cur)

    rows = []
    for w in workloads:
        actual = tag_map.get(w["name"], 0.0)
        t_diff = _telstra_share(actual)
        total  = actual + t_diff
        budget = w["budget_monthly"] or 0.0
        rows.append({
            "workload":         w["name"],
            "domain":           w["domain"] or "",
            "department":       w["department"] or "",
            "budget_manager":   w["budget_manager"] or "",
            "budget_monthly":   budget,
            "actual":           actual,
            "telstra_diff":     t_diff,
            "total":            total,
            "deviation_to_budget": total - budget if budget else None,
        })

    # Other row
    other_t_diff = _telstra_share(other_actual)
    other_total  = other_actual + other_t_diff
    rows.append({
        "workload":         "Other",
        "domain":           "ALL",
        "department":       "",
        "budget_manager":   "",
        "budget_monthly":   None,
        "actual":           other_actual,
        "telstra_diff":     other_t_diff,
        "total":            other_total,
        "deviation_to_budget": None,
    })

    total_finops   = sum(r["total"] for r in rows)
    deviation_fc   = total_finops - forecast if forecast else None

    return {
        "month":                 month,
        "telstra_invoice":       telstra_invoice,
        "forecast":              forecast,
        "total_cur_actual":      total_cur,
        "total_telstra_diff":    telstra_diff_total,
        "total_finops":          total_finops,
        "deviation_to_forecast": deviation_fc,
        "rows":                  rows,
    }


def compute_multi_month(months: list[str]) -> dict[str, Any]:
    """
    Compute run cost for multiple months and return a matrix suitable for
    the overview table (workloads as rows, months as columns).
    """
    results = {m: compute_run_cost(m) for m in months}
    if not results:
        return {"months": [], "workloads": [], "rows": [], "totals": {}}

    # Collect all workload names (preserving order: named first, Other last)
    seen: list[str] = []
    for m in months:
        for r in results[m]["rows"]:
            if r["workload"] not in seen:
                seen.append(r["workload"])

    matrix_rows = []
    for wl in seen:
        row = {"workload": wl, "months": {}}
        for m in months:
            month_data = {r["workload"]: r for r in results[m]["rows"]}
            entry = month_data.get(wl)
            row["months"][m] = {
                "actual":       entry["actual"]       if entry else 0,
                "telstra_diff": entry["telstra_diff"] if entry else 0,
                "total":        entry["total"]        if entry else 0,
            }
        matrix_rows.append(row)

    totals = {}
    for m in months:
        r = results[m]
        totals[m] = {
            "total_cur_actual":   r["total_cur_actual"],
            "total_finops":       r["total_finops"],
            "telstra_invoice":    r["telstra_invoice"],
            "forecast":           r["forecast"],
            "deviation_forecast": r["deviation_to_forecast"],
        }

    return {
        "months":    months,
        "workloads": seen,
        "rows":      matrix_rows,
        "totals":    totals,
    }
