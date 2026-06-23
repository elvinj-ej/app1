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
 * POST: Upload CUR data.
 * Body: { filename, period_start, period_end, rows: [{workload_name, amount, ...}] }
 *
 * This creates the upload record and upserts workload_monthly records.
 * For each row it tries to match the workload name to an existing workload.
 * Unmatched rows are aggregated under an "Others" workload if one exists.
 */
export async function POST(req: NextRequest) {
  const body = await req.json();
  const { filename, period_start, period_end, rows } = body;
  const admin = getAdminClient();

  const { data: { user } } = await supabase.auth.getUser();

  // Determine FY year and month from period_end
  const periodDate = new Date(period_end);
  const calMonth = periodDate.getMonth() + 1;
  const calYear = periodDate.getFullYear();
  const fyYear = calMonth >= 7 ? calYear : calYear - 1;
  const monthInFy = calMonth >= 7 ? calMonth - 6 : calMonth + 6;

  // Load all workloads
  const { data: workloads } = await admin.from("workloads").select("id, name").eq("is_active", true);
  const workloadMap = new Map((workloads ?? []).map((w: { id: number; name: string }) => [w.name.toLowerCase(), w.id]));

  // Aggregate amounts by workload
  const totals = new Map<number, number>();
  let othersTotal = 0;

  for (const row of (rows ?? [])) {
    const name = (row.workload_name ?? "").toLowerCase();
    const amount = parseFloat(row.amount ?? 0);
    const wid = workloadMap.get(name);
    if (wid) {
      totals.set(wid, (totals.get(wid) ?? 0) + amount);
    } else {
      othersTotal += amount;
    }
  }

  // Upsert Others workload amount
  const othersId = workloadMap.get("others");
  if (othersId && othersTotal > 0) {
    totals.set(othersId, (totals.get(othersId) ?? 0) + othersTotal);
  }

  // Upsert workload_monthly rows
  for (const [workloadId, amount] of totals.entries()) {
    await admin.from("workload_monthly").upsert({
      workload_id: workloadId,
      fy_year: fyYear,
      month_in_fy: monthInFy,
      cur_amount: parseFloat(amount.toFixed(2)),
      updated_at: new Date().toISOString(),
    }, { onConflict: "workload_id,fy_year,month_in_fy", ignoreDuplicates: false });
  }

  // Save upload record
  const { data: upload, error } = await admin.from("cur_uploads").insert({
    uploaded_by: user?.id ?? null,
    period_start,
    period_end,
    filename: filename ?? null,
    row_count: (rows ?? []).length,
    processed: true,
    data: rows ?? [],
  }).select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ upload, workloads_updated: totals.size });
}
