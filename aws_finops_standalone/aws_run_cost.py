"""
Computation engine matching AWS_Run Cost tab logic:

For each month:
  1. Actual per workload  = SUM(cur_data.amount WHERE category='monthly_expense' AND workloads_tag=name)
  2. Total CUR            = SUM of all monthly_expense amounts for the month
  3. Other (Consumption)  = Total CUR − SUM(named workload actuals)
  4. Telstra Diff total   = Telstra Invoice − Total CUR
  5. Telstra Diff per row = Diff_total × (row_actual / Total_CUR)
  6. Total per row        = Actual + Telstra Diff
  7. Deviation            = Total − Budget/mo  (positive = over budget)

Cost categories: 'Consumption' (Run Cost rows 17-35) and 'Project' (rows 39-43).
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


def compute(month: str) -> dict:
    with get_conn() as conn:
        # All monthly_expense amounts grouped by workloads_tag
        cur_rows = conn.execute(
            "SELECT workloads_tag, SUM(amount) AS actual "
            "FROM cur_data WHERE month=? AND category='monthly_expense' "
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

    # Build tag → actual map (case-insensitive match)
    tag_actual: dict[str, float] = {}
    for r in cur_rows:
        tag = (r["workloads_tag"] or "").strip()
        tag_actual[tag] = float(r["actual"] or 0)

    total_cur = sum(tag_actual.values())

    # Match CUR tags to workload names (exact first, then case-insensitive)
    workload_names = {w["name"] for w in workloads}

    def resolve(tag: str) -> str | None:
        if tag in workload_names:
            return tag
        return next((n for n in workload_names if n.lower() == tag.lower()), None)

    workload_actual: dict[str, float] = {}
    for tag, amt in tag_actual.items():
        name = resolve(tag)
        if name:
            workload_actual[name] = workload_actual.get(name, 0) + amt

    named_total = sum(workload_actual.values())
    other_actual = max(0.0, total_cur - named_total)

    telstra_invoice = float((mi["telstra_invoice"] if mi else None) or 0)
    forecast_run    = (mi["forecast_run"]    if mi else None)
    forecast_project = (mi["forecast_project"] if mi else None)

    telstra_diff_total = telstra_invoice - total_cur if telstra_invoice else 0.0

    def tdiff(actual: float) -> float:
        if total_cur == 0 or not telstra_invoice:
            return 0.0
        return telstra_diff_total * (actual / total_cur)

    consumption_rows = []
    project_rows = []

    for w in workloads:
        actual = workload_actual.get(w["name"], 0.0)
        td     = tdiff(actual)
        total  = actual + td
        budget = float(w["budget_monthly"] or 0)
        row = {
            "workload":       w["name"],
            "domain":         w["domain"] or "",
            "cost_category":  w["cost_category"],
            "budget_manager": w["budget_manager"] or "",
            "description":    w["description"] or "",
            "budget_monthly": budget or None,
            "actual":         actual,
            "telstra_diff":   td,
            "total":          total,
            "deviation":      (total - budget) if budget else None,
        }
        if w["cost_category"] == "Project":
            project_rows.append(row)
        else:
            consumption_rows.append(row)

    # Other row (untagged/unmatched CUR spend)
    other_td = tdiff(other_actual)
    other_row = {
        "workload":       "Other",
        "domain":         "ALL",
        "cost_category":  "Consumption",
        "budget_manager": "",
        "description":    "Untagged or unmatched CUR spend",
        "budget_monthly": None,
        "actual":         other_actual,
        "telstra_diff":   other_td,
        "total":          other_actual + other_td,
        "deviation":      None,
    }
    consumption_rows.append(other_row)

    total_consumption_actual = sum(r["actual"] for r in consumption_rows)
    total_project_actual     = sum(r["actual"] for r in project_rows)
    total_consumption_total  = sum(r["total"]  for r in consumption_rows)
    total_project_total      = sum(r["total"]  for r in project_rows)
    grand_total              = total_consumption_total + total_project_total

    return {
        "month":                   month,
        "telstra_invoice":         telstra_invoice,
        "telstra_diff_total":      telstra_diff_total,
        "forecast_run":            forecast_run,
        "forecast_project":        forecast_project,
        "total_cur":               total_cur,
        "total_consumption_actual": total_consumption_actual,
        "total_project_actual":    total_project_actual,
        "total_consumption_total": total_consumption_total,
        "total_project_total":     total_project_total,
        "grand_total":             grand_total,
        "deviation_run":           (total_consumption_total - forecast_run)    if forecast_run    else None,
        "deviation_project":       (total_project_total     - forecast_project) if forecast_project else None,
        "consumption_rows":        consumption_rows,
        "project_rows":            project_rows,
    }
