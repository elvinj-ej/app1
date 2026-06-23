export const dynamic = "force-dynamic";
import { NextRequest, NextResponse } from "next/server";
import { getAdminClient, supabase } from "@/lib/db/client";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const fyYear = searchParams.get("fy_year");
  let q = supabase.from("invoice_adjustments").select("*").order("month_in_fy");
  if (fyYear) q = q.eq("fy_year", Number(fyYear));
  const { data } = await q;
  return NextResponse.json(data ?? []);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const admin = getAdminClient();
  const { data, error } = await admin
    .from("invoice_adjustments")
    .upsert(body, { onConflict: "fy_year,month_in_fy" })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}
