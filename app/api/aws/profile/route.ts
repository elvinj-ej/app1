export const dynamic = "force-dynamic";
import { NextResponse } from "next/server";
import { supabase } from "@/lib/db/client";

export async function GET() {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json(null);
  const { data } = await supabase
    .from("profiles")
    .select("id, display_name, email, role, created_at")
    .eq("id", user.id)
    .single();
  return NextResponse.json(data);
}
