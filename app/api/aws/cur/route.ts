export const dynamic = "force-dynamic";
import { NextRequest, NextResponse } from "next/server";
import { getAdminClient, supabase } from "@/lib/db/client";

export async function GET() {
  const { data } = await supabase
    .from("cur_uploads")
    .select("id, filename, period_start, period_end, row_count, processed, created_at")
    .order("created_at", { ascending: false })
    .limit(50);
  return NextResponse.json(data ?? []);
}

/**
 * POST: Upload AWSCUR data in the standard Cochlear CUR format.
 *
 * The CUR CSV has:
 *   - Row 1: headers — account_id, account_name, workloads_tag, outcomegroup_tag, category,
 *             then date columns as Excel serial numbers (e.g. 45870 = 2025-10-01)
 *   - Row 2: "forecast" summary row (skip)
 *   - Row 3: "sum_monthly_expense" summary row (skip)
 *   - Row 4: "sum_marketplace" summary row (skip)
 *   - Row 5+: Per-account rows with monthly amounts
 *
 * We aggregate by (workloads_tag, calendar_month_year) and map to workloads by name.
 * Accounts whose workloads_tag is NOT in the Exclusion list → aggregated under "Others".
 *
 * Body: { filename, rows: [{ account_id, account_name, workloads_tag, category, ...dateKey: amount }] }
 * where dateKey is an Excel serial number string.
 *
 * Alternatively: body can contain the raw CSV text as { csv: "..." }.
 */
export async function POST(req: NextRequest) {
  const admin = getAdminClient();
  const { data: { user } } = await supabase.auth.getUser();

  const contentType = req.headers.get("content-type") ?? "";
  let rows: Record<string, string>[] = [];
  let filename: string | null = null;

  if (contentType.includes("multipart/form-data")) {
    const form = await req.formData();
    const file = form.get("file") as File | null;
    if (!file) return NextResponse.json({ error: "No file uploaded" }, { status: 400 });
    filename = file.name;
    const text = await file.text();
    rows = parseCsv(text);
  } else {
    const body = await req.json();
    rows = body.rows ?? [];
    filename = body.filename ?? null;
  }

  // Load all active workloads for name matching
  const { data: workloads } = await admin
    .from("workloads")
    .select("id, name, is_networking")
    .eq("is_active", true);

  // Build lookup: lowercase name → workload id
  const workloadMap = new Map<string, number>();
  let othersId: number | null = null;
  for (const w of workloads ?? []) {
    workloadMap.set(w.name.toLowerCase(), w.id);
    if (w.name.toLowerCase() === "others") othersId = w.id;
  }

  // Filter rows: only monthly_expense rows with a workloads_tag
  const dataRows = rows.filter(
    (r) => r.category === "monthly_expense" && r.workloads_tag
  );

  // Find all date-keyed columns (numeric keys = Excel serial dates)
  const sampleRow = dataRows[0] ?? rows[0] ?? {};
  const dateKeys = Object.keys(sampleRow).filter((k) => /^\d{5}$/.test(k));

  // Convert Excel serial date → { fy_year, month_in_fy }
  function excelDateToFyMonth(serial: number): { fyYear: number; monthInFy: number; calYear: number; calMonth: number } | null {
    // Excel epoch: 1900-01-01 = 1 (with known off-by-one bug: serial 1 = Jan 1 1900)
    const msPerDay = 86400000;
    const excelEpoch = new Date(Date.UTC(1899, 11, 30)).getTime();
    const d = new Date(excelEpoch + serial * msPerDay);
    const calMonth = d.getUTCMonth() + 1; // 1-12
    const calYear = d.getUTCFullYear();
    const fyYear = calMonth >= 7 ? calYear : calYear - 1;
    const monthInFy = calMonth >= 7 ? calMonth - 6 : calMonth + 6;
    return { fyYear, monthInFy, calYear, calMonth };
  }

  // Aggregate: Map<workload_id, Map<monthKey, amount>>
  type MonthKey = string; // "fyYear_monthInFy"
  const totals = new Map<number, Map<MonthKey, number>>();

  function addAmount(wid: number, monthKey: MonthKey, amount: number) {
    if (!totals.has(wid)) totals.set(wid, new Map());
    totals.get(wid)!.set(monthKey, (totals.get(wid)!.get(monthKey) ?? 0) + amount);
  }

  for (const row of dataRows) {
    const tag = (row.workloads_tag ?? "").toLowerCase().trim();
    const wid = workloadMap.get(tag) ?? othersId;
    if (!wid) continue;

    for (const dk of dateKeys) {
      const serial = parseInt(dk, 10);
      const period = excelDateToFyMonth(serial);
      if (!period) continue;
      const amount = parseFloat(row[dk] ?? "0") || 0;
      if (amount === 0) continue;
      const monthKey = `${period.fyYear}_${period.monthInFy}`;
      addAmount(wid, monthKey, amount);
    }
  }

  // Upsert workload_monthly rows — update cur_amount (sum from CUR)
  let updatedCount = 0;
  for (const [workloadId, monthMap] of totals) {
    for (const [monthKey, amount] of monthMap) {
      const [fyYearStr, monthInFyStr] = monthKey.split("_");
      const fyYear = parseInt(fyYearStr, 10);
      const monthInFy = parseInt(monthInFyStr, 10);

      const { data: existing } = await admin
        .from("workload_monthly")
        .select("id, cur_amount")
        .eq("workload_id", workloadId)
        .eq("fy_year", fyYear)
        .eq("month_in_fy", monthInFy)
        .maybeSingle();

      const roundedAmount = parseFloat(amount.toFixed(2));

      if (existing) {
        await admin.from("workload_monthly").update({
          cur_amount: roundedAmount,
          updated_at: new Date().toISOString(),
        }).eq("id", existing.id);
      } else {
        await admin.from("workload_monthly").insert({
          workload_id: workloadId,
          fy_year: fyYear,
          month_in_fy: monthInFy,
          cur_amount: roundedAmount,
          forecast_amount: 0,
          updated_at: new Date().toISOString(),
        });
      }
      updatedCount++;
    }
  }

  // Redistribute shared costs for affected periods
  const affectedPeriods = new Set<string>();
  for (const monthMap of totals.values()) {
    for (const mk of monthMap.keys()) affectedPeriods.add(mk);
  }
  for (const mk of affectedPeriods) {
    const [fyYearStr, monthInFyStr] = mk.split("_");
    // Import redistributeSharedCosts inline to avoid circular dep issues in API route
    await redistributeAfterImport(admin, parseInt(fyYearStr, 10), parseInt(monthInFyStr, 10));
  }

  // Save upload record
  const { data: upload, error } = await admin.from("cur_uploads").insert({
    uploaded_by: user?.id ?? null,
    period_start: new Date().toISOString().slice(0, 10),
    period_end: new Date().toISOString().slice(0, 10),
    filename,
    row_count: dataRows.length,
    processed: true,
    data: [], // don't store raw data to keep DB small
  }).select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ upload, workloads_updated: totals.size, rows_updated: updatedCount });
}

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
  return lines.slice(1).map((line) => {
    const vals = line.match(/(".*?"|[^,]+|(?<=,)(?=,)|(?<=,)$|^(?=,))/g) ?? line.split(",");
    const row: Record<string, string> = {};
    headers.forEach((h, i) => {
      row[h] = (vals[i] ?? "").trim().replace(/^"|"$/g, "");
    });
    return row;
  });
}

// Inline mini version of redistributeSharedCosts to avoid ESM issues in API route
async function redistributeAfterImport(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  admin: any, fyYear: number, monthInFy: number
) {
  const { data: allWorkloads } = await admin
    .from("workloads")
    .select("id, is_networking")
    .eq("is_active", true);

  const networkingIds = new Set((allWorkloads ?? []).filter((w: { is_networking: boolean }) => w.is_networking).map((w: { id: number }) => w.id));
  const regularIds = new Set((allWorkloads ?? []).filter((w: { is_networking: boolean }) => !w.is_networking).map((w: { id: number }) => w.id));

  const { data: rows } = await admin
    .from("workload_monthly")
    .select("id, workload_id, cur_amount, forecast_amount, invoiced_amount")
    .eq("fy_year", fyYear)
    .eq("month_in_fy", monthInFy);
  if (!rows?.length) return;

  const networkingRows = rows.filter((r: { workload_id: number }) => networkingIds.has(r.workload_id));
  const regularRows = rows.filter((r: { workload_id: number }) => regularIds.has(r.workload_id));

  const totalNetworking = networkingRows.reduce(
    (s: number, r: { invoiced_amount: number | null; cur_amount: number; forecast_amount: number }) =>
      s + (r.invoiced_amount ?? r.cur_amount ?? r.forecast_amount ?? 0), 0
  );

  const { data: adjRow } = await admin
    .from("invoice_adjustments")
    .select("amount")
    .eq("fy_year", fyYear)
    .eq("month_in_fy", monthInFy)
    .maybeSingle();
  const totalAdjustment = adjRow?.amount ?? 0;

  const totalBase = regularRows.reduce(
    (s: number, r: { invoiced_amount: number | null; cur_amount: number; forecast_amount: number }) =>
      s + (r.invoiced_amount ?? r.cur_amount ?? r.forecast_amount ?? 0), 0
  );

  for (const row of regularRows) {
    const base = (row as { invoiced_amount: number | null; cur_amount: number; forecast_amount: number }).invoiced_amount
      ?? (row as { cur_amount: number }).cur_amount
      ?? (row as { forecast_amount: number }).forecast_amount ?? 0;
    const ratio = totalBase > 0 ? base / totalBase : 1 / regularRows.length;
    await admin.from("workload_monthly").update({
      networking_share: parseFloat((totalNetworking * ratio).toFixed(2)),
      invoice_adjustment_share: parseFloat((totalAdjustment * ratio).toFixed(2)),
      updated_at: new Date().toISOString(),
    }).eq("id", (row as { id: number }).id);
  }

  for (const row of networkingRows) {
    await admin.from("workload_monthly").update({
      networking_share: 0,
      invoice_adjustment_share: 0,
    }).eq("id", (row as { id: number }).id);
  }
}
