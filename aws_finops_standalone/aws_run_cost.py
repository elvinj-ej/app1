"""
Computation engine matching AWS_Run Cost tab logic.

Actual per workload = monthly_expense + marketplace + marketplace_adjustment
total_cur           = sum of all net actuals (used for Telstra Diff ratio)
Telstra Diff total  = Telstra Invoice − total_cur
Telstra Diff/row    = Diff_total × (row_actual / total_cur)
Total/row           = actual + telstra_diff
Deviation           = total − budget  (positive = over budget)
"""
from __future__ import annotations
from aws_db import get_conn


def get_available_months():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT month FROM cur_data WHERE category='monthly_expense' ORDER BY month"
        ).fetchall()
    return [r["month"] for r in rows]


def get_workloads():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name, domain, cost_category, budget_manager, description, budget_monthly, sort_order "
            "FROM workloads ORDER BY sort_order, name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_monthly_input(month):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT telstra_invoice, forecast_run, forecast_project FROM monthly_inputs WHERE month=?",
            (month,),
        ).fetchone()
    return dict(row) if row else {"telstra_invoice": None, "forecast_run": None, "forecast_project": None}


def _build_tag_map(rows):
    """Group CUR rows into {tag: amount}."""
    m: dict[str, float] = {}
    for r in rows:
        tag = (r["workloads_tag"] or "").strip()
        m[tag] = m.get(tag, 0.0) + float(r["actual"] or 0)
    return m


def compute(month: str) -> dict:
    with get_conn() as conn:
        expense_rows = conn.execute(
            "SELECT workloads_tag, SUM(amount) AS actual "
            "FROM cur_data WHERE month=? AND category='monthly_expense' "
            "GROUP BY workloads_tag",
            (month,),
        ).fetchall()

        marketplace_rows = conn.execute(
            "SELECT workloads_tag, SUM(amount) AS actual "
            "FROM cur_data WHERE month=? AND category='marketplace' "
            "GROUP BY workloads_tag",
            (month,),
        ).fetchall()

        workloads = conn.execute(
            "SELECT name, domain, cost_category, budget_manager, description, budget_monthly "
            "FROM workloads ORDER BY sort_order, name"
        ).fetchall()

        mi = conn.execute(
            "SELECT telstra_invoice, forecast_run, forecast_project FROM monthly_inputs WHERE month=?",
            (month,),
        ).fetchone()

        adj_rows = conn.execute(
            "SELECT workload, adjustment, note FROM marketplace_adjustments WHERE month=?",
            (month,),
        ).fetchall()

    tag_expense    = _build_tag_map(expense_rows)
    tag_marketplace = _build_tag_map(marketplace_rows)
    adj_map = {r["workload"]: (float(r["adjustment"] or 0), r["note"] or "") for r in adj_rows}

    workload_names = {w["name"] for w in workloads}

    def resolve(tag: str) -> str | None:
        if tag in workload_names:
            return tag
        return next((n for n in workload_names if n.lower() == tag.lower()), None)

    # Aggregate expense + marketplace per named workload
    workload_expense:     dict[str, float] = {}
    workload_marketplace: dict[str, float] = {}

    for tag, amt in tag_expense.items():
        name = resolve(tag)
        if name:
            workload_expense[name] = workload_expense.get(name, 0.0) + amt

    for tag, amt in tag_marketplace.items():
        name = resolve(tag)
        if name:
            workload_marketplace[name] = workload_marketplace.get(name, 0.0) + amt

    # total_cur = all expense + all marketplace (net of adjustments)
    total_expense_cur     = sum(tag_expense.values())
    total_marketplace_cur = sum(tag_marketplace.values())
    total_adj             = sum(a for a, _ in adj_map.values())
    total_cur             = total_expense_cur + total_marketplace_cur + total_adj

    named_expense     = sum(workload_expense.values())
    named_marketplace = sum(workload_marketplace.values())
    named_adj         = sum(adj_map.get(w["name"], (0.0, ""))[0] for w in workloads)
    other_actual      = max(0.0,
        (total_expense_cur - named_expense) +
        (total_marketplace_cur - named_marketplace)
    )

    telstra_invoice  = float((mi["telstra_invoice"]  if mi else None) or 0)
    forecast_run     = (mi["forecast_run"]     if mi else None)
    forecast_project = (mi["forecast_project"] if mi else None)

    telstra_diff_total = telstra_invoice - total_cur if telstra_invoice else 0.0

    def tdiff(actual: float) -> float:
        if total_cur == 0 or not telstra_invoice:
            return 0.0
        return telstra_diff_total * (actual / total_cur)

    consumption_rows = []
    project_rows = []

    for w in workloads:
        expense     = workload_expense.get(w["name"], 0.0)
        marketplace = workload_marketplace.get(w["name"], 0.0)
        adj, adj_note = adj_map.get(w["name"], (0.0, ""))
        actual = expense + marketplace + adj
        td     = tdiff(actual)
        total  = actual + td
        budget = float(w["budget_monthly"] or 0)
        row = {
            "workload":          w["name"],
            "domain":            w["domain"] or "",
            "cost_category":     w["cost_category"],
            "budget_manager":    w["budget_manager"] or "",
            "description":       w["description"] or "",
            "budget_monthly":    budget or None,
            "actual_expense":    expense,
            "actual_marketplace": marketplace,
            "marketplace_adjustment": adj,
            "marketplace_adj_note":   adj_note,
            "actual":            actual,
            "telstra_diff":      td,
            "total":             total,
            "deviation":         (total - budget) if budget else None,
        }
        if w["cost_category"] == "Project":
            project_rows.append(row)
        else:
            consumption_rows.append(row)

    # Other row — untagged/unmatched CUR spend (no adjustments applied)
    other_td  = tdiff(other_actual)
    other_row = {
        "workload":           "Other",
        "domain":             "ALL",
        "cost_category":      "Consumption",
        "budget_manager":     "",
        "description":        "Untagged or unmatched CUR spend",
        "budget_monthly":     None,
        "actual_expense":     other_actual,
        "actual_marketplace": 0.0,
        "marketplace_adjustment": 0.0,
        "marketplace_adj_note":   "",
        "actual":             other_actual,
        "telstra_diff":       other_td,
        "total":              other_actual + other_td,
        "deviation":          None,
    }
    consumption_rows.append(other_row)

    total_consumption_actual  = sum(r["actual"]         for r in consumption_rows)
    total_project_actual      = sum(r["actual"]         for r in project_rows)
    total_consumption_total   = sum(r["total"]          for r in consumption_rows)
    total_project_total       = sum(r["total"]          for r in project_rows)
    total_consumption_budget  = sum(r["budget_monthly"] for r in consumption_rows if r["budget_monthly"])
    total_project_budget      = sum(r["budget_monthly"] for r in project_rows     if r["budget_monthly"])
    grand_total               = total_consumption_total + total_project_total

    return {
        "month":                    month,
        "telstra_invoice":          telstra_invoice,
        "telstra_diff_total":       telstra_diff_total,
        "forecast_run":             forecast_run,
        "forecast_project":         forecast_project,
        "total_cur":                total_cur,
        "total_expense_cur":        total_expense_cur,
        "total_marketplace_cur":    total_marketplace_cur,
        "total_consumption_actual": total_consumption_actual,
        "total_project_actual":     total_project_actual,
        "total_consumption_total":  total_consumption_total,
        "total_project_total":      total_project_total,
        "total_consumption_budget": total_consumption_budget,
        "total_project_budget":     total_project_budget,
        "grand_total":              grand_total,
        "deviation_run":            (total_consumption_total - forecast_run)     if forecast_run     else None,
        "deviation_project":        (total_project_total     - forecast_project) if forecast_project else None,
        "consumption_rows":         consumption_rows,
        "project_rows":             project_rows,
    }
