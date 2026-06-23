import { supabase, getAdminClient } from "./client";
import type {
  Workload, WorkloadMonthly, WorkloadConsumption,
  NetworkingCost, InvoiceAdjustment, Profile
} from "./aws-types";

// ── Profile ──────────────────────────────────────────────────

export async function getProfile(userId: string): Promise<Profile | null> {
  const { data } = await supabase
    .from("profiles")
    .select("id, display_name, email, role, created_at")
    .eq("id", userId)
    .single();
  return data as Profile | null;
}

export async function listProfiles(): Promise<Profile[]> {
  const admin = getAdminClient();
  const { data } = await admin
    .from("profiles")
    .select("id, display_name, email, role, created_at")
    .order("email");
  return (data ?? []) as Profile[];
}

// ── Workloads ────────────────────────────────────────────────

export async function listWorkloads(activeOnly = true): Promise<Workload[]> {
  let q = supabase.from("workloads").select("*").order("name");
  if (activeOnly) q = q.eq("is_active", true);
  const { data } = await q;
  return (data ?? []) as Workload[];
}

export async function upsertWorkload(w: Partial<Workload> & { name: string }) {
  const admin = getAdminClient();
  return admin.from("workloads").upsert(w, { onConflict: "name" }).select().single();
}

export async function deleteWorkload(id: number) {
  const admin = getAdminClient();
  return admin.from("workloads").update({ is_active: false }).eq("id", id);
}

// ── Monthly Data ─────────────────────────────────────────────

export async function getWorkloadMonthly(
  workloadId: number, fyYear: number
): Promise<WorkloadMonthly[]> {
  const { data } = await supabase
    .from("workload_monthly")
    .select("*")
    .eq("workload_id", workloadId)
    .eq("fy_year", fyYear)
    .order("month_in_fy");
  return (data ?? []) as WorkloadMonthly[];
}

export async function upsertWorkloadMonthly(row: Omit<WorkloadMonthly, "id" | "updated_at">) {
  const admin = getAdminClient();
  return admin
    .from("workload_monthly")
    .upsert({ ...row, updated_at: new Date().toISOString() }, {
      onConflict: "workload_id,fy_year,month_in_fy"
    })
    .select()
    .single();
}

export async function setInvoicedAmount(
  workloadId: number, fyYear: number, monthInFy: number, invoicedAmount: number
) {
  const admin = getAdminClient();
  return admin
    .from("workload_monthly")
    .update({ invoiced_amount: invoicedAmount, status: "invoiced", updated_at: new Date().toISOString() })
    .match({ workload_id: workloadId, fy_year: fyYear, month_in_fy: monthInFy });
}

// ── Consumption View ─────────────────────────────────────────

export async function getConsumption(fyYear: number): Promise<WorkloadConsumption[]> {
  const { data } = await supabase
    .from("workload_consumption")
    .select("*")
    .eq("fy_year", fyYear)
    .order("workload_name")
    .order("month_in_fy");
  return (data ?? []) as WorkloadConsumption[];
}

export async function getWorkloadConsumption(
  workloadId: number, fyYear: number
): Promise<WorkloadConsumption[]> {
  const { data } = await supabase
    .from("workload_consumption")
    .select("*")
    .eq("workload_id", workloadId)
    .eq("fy_year", fyYear)
    .order("month_in_fy");
  return (data ?? []) as WorkloadConsumption[];
}

export async function getMyWorkloadsConsumption(fyYear: number): Promise<WorkloadConsumption[]> {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return [];
  const { data } = await supabase
    .from("workload_consumption")
    .select("*")
    .eq("owner_user_id", user.id)
    .eq("fy_year", fyYear)
    .order("workload_name")
    .order("month_in_fy");
  return (data ?? []) as WorkloadConsumption[];
}

// ── Networking Costs ─────────────────────────────────────────

export async function getNetworkingCosts(fyYear: number): Promise<NetworkingCost[]> {
  const { data } = await supabase
    .from("networking_costs")
    .select("*")
    .eq("fy_year", fyYear)
    .order("month_in_fy");
  return (data ?? []) as NetworkingCost[];
}

export async function upsertNetworkingCost(nc: Omit<NetworkingCost, "id" | "created_at">) {
  const admin = getAdminClient();
  return admin
    .from("networking_costs")
    .upsert(nc, { onConflict: "fy_year,month_in_fy,description" })
    .select()
    .single();
}

// ── Invoice Adjustments ──────────────────────────────────────

export async function getInvoiceAdjustments(fyYear: number): Promise<InvoiceAdjustment[]> {
  const { data } = await supabase
    .from("invoice_adjustments")
    .select("*")
    .eq("fy_year", fyYear)
    .order("month_in_fy");
  return (data ?? []) as InvoiceAdjustment[];
}

export async function upsertInvoiceAdjustment(ia: Omit<InvoiceAdjustment, "id" | "created_at">) {
  const admin = getAdminClient();
  return admin
    .from("invoice_adjustments")
    .upsert(ia, { onConflict: "fy_year,month_in_fy" })
    .select()
    .single();
}

// ── Redistribute shared networking & invoice adjustment shares ──
// The 4 networking workloads (is_networking=true: AWS Networks, Billing,
// Network F5, Network Firewall) have their monthly CUR costs treated as
// shared infrastructure. After CUR import or manual update, call this to:
//   1. Sum the networking workloads' actual/forecast for the month
//   2. Distribute that total proportionally across all NON-networking workloads
//   3. Also distribute the global invoice adjustment (row 16 in Excel) proportionally
export async function redistributeSharedCosts(fyYear: number, monthInFy: number) {
  const admin = getAdminClient();

  // Identify networking vs regular workloads
  const { data: allWorkloads } = await admin
    .from("workloads")
    .select("id, is_networking")
    .eq("is_active", true);

  const networkingIds = new Set((allWorkloads ?? []).filter((w: { is_networking: boolean }) => w.is_networking).map((w: { id: number }) => w.id));
  const regularIds = new Set((allWorkloads ?? []).filter((w: { is_networking: boolean }) => !w.is_networking).map((w: { id: number }) => w.id));

  // Get all monthly rows for the period
  const { data: rows } = await admin
    .from("workload_monthly")
    .select("id, workload_id, cur_amount, forecast_amount, invoiced_amount")
    .eq("fy_year", fyYear)
    .eq("month_in_fy", monthInFy);

  if (!rows?.length) return;

  // Sum networking workloads' effective cost (invoiced if available, else CUR, else forecast)
  const networkingRows = (rows ?? []).filter((r: { workload_id: number }) => networkingIds.has(r.workload_id));
  const totalNetworking = networkingRows.reduce(
    (s: number, r: { invoiced_amount: number | null; cur_amount: number; forecast_amount: number }) =>
      s + (r.invoiced_amount ?? r.cur_amount ?? r.forecast_amount ?? 0), 0
  );

  // Also add any manual networking_costs entries (legacy / override)
  const { data: netRows } = await admin
    .from("networking_costs")
    .select("amount")
    .eq("fy_year", fyYear)
    .eq("month_in_fy", monthInFy);
  const manualNetworking = (netRows ?? []).reduce((s: number, r: { amount: number }) => s + (r.amount ?? 0), 0);

  const totalSharedNetworking = totalNetworking + manualNetworking;

  // Get invoice adjustment (row 16 in Excel: total Telstra invoice diff for the month)
  const { data: adjRow } = await admin
    .from("invoice_adjustments")
    .select("amount")
    .eq("fy_year", fyYear)
    .eq("month_in_fy", monthInFy)
    .maybeSingle();
  const totalAdjustment = adjRow?.amount ?? 0;

  // Distribute proportionally across regular (non-networking) workloads by their consumption
  const regularRows = (rows ?? []).filter((r: { workload_id: number }) => regularIds.has(r.workload_id));
  const totalBaseConsumption = regularRows.reduce(
    (s: number, r: { invoiced_amount: number | null; cur_amount: number; forecast_amount: number }) =>
      s + (r.invoiced_amount ?? r.cur_amount ?? r.forecast_amount ?? 0), 0
  );

  for (const row of regularRows) {
    const base = (row as { invoiced_amount: number | null; cur_amount: number; forecast_amount: number }).invoiced_amount
      ?? (row as { cur_amount: number }).cur_amount
      ?? (row as { forecast_amount: number }).forecast_amount ?? 0;
    const ratio = totalBaseConsumption > 0 ? base / totalBaseConsumption : 1 / regularRows.length;
    await admin.from("workload_monthly").update({
      networking_share: parseFloat((totalSharedNetworking * ratio).toFixed(2)),
      invoice_adjustment_share: parseFloat((totalAdjustment * ratio).toFixed(2)),
      updated_at: new Date().toISOString(),
    }).eq("id", (row as { id: number }).id);
  }

  // Networking workloads get 0 allocation (they ARE the shared cost)
  for (const row of networkingRows) {
    await admin.from("workload_monthly").update({
      networking_share: 0,
      invoice_adjustment_share: 0,
      updated_at: new Date().toISOString(),
    }).eq("id", (row as { id: number }).id);
  }
}
