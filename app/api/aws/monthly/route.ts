export const dynamic = "force-dynamic";
import { NextRequest, NextResponse } from "next/server";
import { getAdminClient, supabase } from "@/lib/db/client";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const fyYear = searchParams.get("fy_year");
  const workloadId = searchParams.get("workload_id");

  let q = supabase.from("workload_consumption").select("*");
  if (fyYear) q = q.eq("fy_year", Number(fyYear));
  if (workloadId) q = q.eq("workload_id", Number(workloadId));
  q = q.order("workload_name").order("month_in_fy");

  const { data, error } = await q;
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data ?? []);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const admin = getAdminClient();
  const { data, error } = await admin
    .from("workload_monthly")
    .upsert({ ...body, updated_at: new Date().toISOString() }, {
      onConflict: "workload_id,fy_year,month_in_fy"
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}

export async function PATCH(req: NextRequest) {
  // Used to set invoiced_amount (marks as invoiced)
  const { workload_id, fy_year, month_in_fy, invoiced_amount } = await req.json();
  const admin = getAdminClient();
  const { data, error } = await admin
    .from("workload_monthly")
    .update({
      invoiced_amount,
      status: "invoiced",
      updated_at: new Date().toISOString(),
    })
    .match({ workload_id, fy_year, month_in_fy })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}
