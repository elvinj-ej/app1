"""
Three-tier cost model:

  Shared Cost accounts (AWS Networks, Billing, Network F5, Network Firewall):
    - Their actual spend is pooled and distributed to Run + Project accounts.
    - They do NOT receive a Telstra Diff allocation themselves.

  Run Cost accounts (Consumption):
    - actual          = own CUR spend (monthly_expense + marketplace + adjustment)
    - shared_alloc    = SharedPool × (own_actual / run_project_total)
    - telstra_diff    = TelstraDiffTotal × (own_actual / run_project_total)
    - finops_total    = actual + shared_alloc + telstra_diff
    - deviation       = finops_total − budget

  Project X-charge: same formula as Run Cost.

  Grand Total (sum of all Run+Project finops_total) = Telstra Invoice.
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
            "SELECT name, domain, cost_category, budget_manager, description, budget_monthly, sort_order, cur_tag "
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
            "SELECT name, domain, cost_category, budget_manager, description, budget_monthly, cur_tag "
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

    tag_expense     = _build_tag_map(expense_rows)
    tag_marketplace = _build_tag_map(marketplace_rows)
    adj_map = {r["workload"]: (float(r["adjustment"] or 0), r["note"] or "") for r in adj_rows}

    workload_names = {w["name"] for w in workloads}
    # cur_tag overrides: maps CUR workloads_tag → workload name
    cur_tag_map: dict[str, str] = {}
    for w in workloads:
        ct = (w["cur_tag"] or "").strip()
        if ct:
            cur_tag_map[ct.lower()] = w["name"]

    def resolve(tag: str) -> str | None:
        tl = tag.lower()
        # 1. Exact cur_tag override match
        if tl in cur_tag_map:
            return cur_tag_map[tl]
        # 2. Exact workload name match
        if tag in workload_names:
            return tag
        # 3. Case-insensitive workload name match
        return next((n for n in workload_names if n.lower() == tl), None)

    workload_expense:     dict[str, float] = {}
    workload_marketplace: dict[str, float] = {}
    unmatched_tags: dict[str, float] = {}   # tag → total unmatched spend

    for tag, amt in tag_expense.items():
        name = resolve(tag)
        if name:
            workload_expense[name] = workload_expense.get(name, 0.0) + amt
        else:
            unmatched_tags[tag] = unmatched_tags.get(tag, 0.0) + amt

    for tag, amt in tag_marketplace.items():
        name = resolve(tag)
        if name:
            workload_marketplace[name] = workload_marketplace.get(name, 0.0) + amt
        else:
            unmatched_tags[tag] = unmatched_tags.get(tag, 0.0) + amt

    def net_actual(name: str) -> float:
        adj, _ = adj_map.get(name, (0.0, ""))
        return workload_expense.get(name, 0.0) + workload_marketplace.get(name, 0.0) + adj

    # Categorise workloads
    shared_wl    = [w for w in workloads if w["cost_category"] == "Shared"]
    run_wl       = [w for w in workloads if w["cost_category"] == "Consumption"]
    project_wl   = [w for w in workloads if w["cost_category"] == "Project"]
    other_cat_wl = [w for w in workloads if w["cost_category"] == "Other"]

    # Shared pool = sum of all Shared account actuals
    shared_pool = sum(net_actual(w["name"]) for w in shared_wl)

    # Named run+project actual total (includes "Other" category — they share the same pool)
    named_run_proj = sum(net_actual(w["name"]) for w in run_wl + project_wl + other_cat_wl)

    # Unmatched CUR spend → goes into Run Cost "Other" row
    total_expense_cur     = sum(tag_expense.values())
    total_marketplace_cur = sum(tag_marketplace.values())
    total_adj             = sum(a for a, _ in adj_map.values())
    # Marketplace purchases paid via separate PO (negative adjustments = removed from Telstra scope)
    total_marketplace_pos_adj = abs(sum(min(0.0, a) for a, _ in adj_map.values()))
    named_all = sum(net_actual(w["name"]) for w in workloads)
    other_actual = max(0.0, total_expense_cur + total_marketplace_cur + total_adj - named_all)

    # Denominator includes all run+project spend (named workloads + Other).
    # Marketplace adjustments already reduce each workload's net_actual so adjusted
    # marketplace is naturally excluded; unadjusted marketplace is naturally included.
    run_proj_total = named_run_proj + other_actual

    # total_cur = shared + run + project + other
    total_cur = shared_pool + run_proj_total

    telstra_invoice  = float((mi["telstra_invoice"]  if mi else None) or 0)
    forecast_run     = (mi["forecast_run"]     if mi else None)
    forecast_project = (mi["forecast_project"] if mi else None)

    # Marketplace adjustments (negative = paid via separate PO, not through Telstra)
    # must reduce the effective invoice by the same amount they reduce total_cur,
    # otherwise telstra_diff is inflated by the full adjustment and spreads that
    # phantom cost across every workload.
    # effective_invoice = invoice + total_adj  (negative adj → reduces invoice)
    # telstra_diff = effective_invoice - total_cur
    #              = (invoice + total_adj) - (original_cur + total_adj)
    #              = invoice - original_cur   ← clean, adjustment-neutral
    effective_invoice  = (telstra_invoice + total_adj) if telstra_invoice else 0.0
    telstra_diff_total = (effective_invoice - total_cur) if telstra_invoice else 0.0

    def allocs(actual: float):
        """(shared_alloc, telstra_diff) proportional to run_proj_total."""
        if run_proj_total == 0:
            return 0.0, 0.0
        ratio = actual / run_proj_total
        return shared_pool * ratio, telstra_diff_total * ratio

    # ── Shared Cost rows ──────────────────────────────────────────────────────
    shared_rows = []
    for w in shared_wl:
        expense     = workload_expense.get(w["name"], 0.0)
        marketplace = workload_marketplace.get(w["name"], 0.0)
        adj, adj_note = adj_map.get(w["name"], (0.0, ""))
        actual = expense + marketplace + adj
        budget = float(w["budget_monthly"] or 0)
        shared_rows.append({
            "workload":               w["name"],
            "domain":                 w["domain"] or "",
            "cost_category":          "Shared",
            "budget_manager":         w["budget_manager"] or "",
            "description":            w["description"] or "",
            "budget_monthly":         budget or None,
            "actual_expense":         expense,
            "actual_marketplace":     marketplace,
            "marketplace_adjustment": adj,
            "marketplace_adj_note":   adj_note,
            "actual":                 actual,
            "deviation":              (actual - budget) if budget else None,
        })

    # ── Run Cost + Project rows ───────────────────────────────────────────────
    consumption_rows = []
    project_rows     = []

    for w, target in [(w, consumption_rows) for w in run_wl] + [(w, project_rows) for w in project_wl]:
        expense     = workload_expense.get(w["name"], 0.0)
        marketplace = workload_marketplace.get(w["name"], 0.0)
        adj, adj_note = adj_map.get(w["name"], (0.0, ""))
        actual = expense + marketplace + adj
        shared_alloc, td = allocs(actual)
        total  = actual + shared_alloc + td
        budget = float(w["budget_monthly"] or 0)
        target.append({
            "workload":               w["name"],
            "domain":                 w["domain"] or "",
            "cost_category":          w["cost_category"],
            "budget_manager":         w["budget_manager"] or "",
            "description":            w["description"] or "",
            "budget_monthly":         budget or None,
            "actual_expense":         expense,
            "actual_marketplace":     marketplace,
            "marketplace_adjustment": adj,
            "marketplace_adj_note":   adj_note,
            "actual":                 actual,
            "shared_alloc":           shared_alloc,
            "telstra_diff":           td,
            "total":                  total,
            "deviation":              (total - budget) if budget else None,
        })

    # Other row: named "Other" category workloads + truly unmatched CUR tags — one combined row
    named_other_actual = sum(net_actual(w["name"]) for w in other_cat_wl)
    combined_other_actual = named_other_actual + other_actual
    combined_other_shared, combined_other_td = allocs(combined_other_actual)

    # Breakdown: named "Other" workloads sorted by spend, then unmatched tags
    named_other_breakdown = sorted(
        [{"tag": w["name"], "amount": net_actual(w["name"])} for w in other_cat_wl if net_actual(w["name"]) != 0],
        key=lambda x: x["amount"], reverse=True
    )
    unmatched_breakdown = sorted(
        [{"tag": t, "amount": a} for t, a in unmatched_tags.items()],
        key=lambda x: x["amount"], reverse=True
    )
    combined_breakdown = named_other_breakdown + unmatched_breakdown

    consumption_rows.append({
        "workload":               "Other",
        "domain":                 "ALL",
        "cost_category":          "Consumption",
        "budget_manager":         "",
        "description":            "Grouped workloads + untagged CUR spend",
        "budget_monthly":         None,
        "actual_expense":         combined_other_actual,
        "actual_marketplace":     0.0,
        "marketplace_adjustment": 0.0,
        "marketplace_adj_note":   "",
        "actual":                 combined_other_actual,
        "shared_alloc":           combined_other_shared,
        "telstra_diff":           combined_other_td,
        "total":                  combined_other_actual + combined_other_shared + combined_other_td,
        "deviation":              None,
        "unmatched_breakdown":    combined_breakdown,
    })

    # ── Totals ────────────────────────────────────────────────────────────────
    total_shared_actual        = sum(r["actual"] for r in shared_rows)
    total_consumption_actual   = sum(r["actual"] for r in consumption_rows)
    total_project_actual       = sum(r["actual"] for r in project_rows)
    total_consumption_finops   = sum(r["total"]  for r in consumption_rows)
    total_project_finops       = sum(r["total"]  for r in project_rows)
    total_consumption_budget   = sum(r["budget_monthly"] for r in consumption_rows if r["budget_monthly"])
    total_project_budget       = sum(r["budget_monthly"] for r in project_rows     if r["budget_monthly"])
    grand_total                = total_consumption_finops + total_project_finops

    return {
        "month":                    month,
        "telstra_invoice":          telstra_invoice,
        "total_adj":                total_adj,
        "total_marketplace_pos_adj": total_marketplace_pos_adj,
        "effective_invoice":        effective_invoice,
        "telstra_diff_total":       telstra_diff_total,
        "forecast_run":             forecast_run,
        "forecast_project":         forecast_project,
        "total_cur":                total_cur,
        "total_expense_cur":        total_expense_cur,
        "total_marketplace_cur":    total_marketplace_cur,
        "shared_pool":              shared_pool,
        "run_proj_total":           run_proj_total,
        "total_shared_actual":      total_shared_actual,
        "total_consumption_actual": total_consumption_actual,
        "total_project_actual":     total_project_actual,
        "total_consumption_finops": total_consumption_finops,
        "total_project_finops":     total_project_finops,
        "total_consumption_budget": total_consumption_budget,
        "total_project_budget":     total_project_budget,
        "grand_total":              grand_total,
        "deviation_run":            (total_consumption_finops - forecast_run)          if forecast_run          else None,
        "deviation_project":        (total_project_finops     - forecast_project)      if forecast_project      else None,
        "deviation_run_vs_budget":  (total_consumption_finops - total_consumption_budget) if total_consumption_budget else None,
        "deviation_proj_vs_budget": (total_project_finops     - total_project_budget)     if total_project_budget     else None,
        "shared_rows":       shared_rows,
        "consumption_rows":  consumption_rows,
        "project_rows":      project_rows,
    }
