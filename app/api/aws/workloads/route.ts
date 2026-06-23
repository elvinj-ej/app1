export const dynamic = "force-dynamic";
import { NextRequest, NextResponse } from "next/server";
import { getAdminClient } from "@/lib/db/client";
import { supabase } from "@/lib/db/client";

export async function GET() {
  const { data } = await supabase.from("workloads").select("*").order("name");
  return NextResponse.json(data ?? []);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const admin = getAdminClient();
  const { data, error } = await admin
    .from("workloads")
    .upsert(body, { onConflict: "name" })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}

export async function DELETE(req: NextRequest) {
  const { id } = await req.json();
  const admin = getAdminClient();
  const { error } = await admin.from("workloads").update({ is_active: false }).eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ ok: true });
}
