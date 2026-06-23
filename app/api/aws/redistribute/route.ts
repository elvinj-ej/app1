export const dynamic = "force-dynamic";
import { NextRequest, NextResponse } from "next/server";
import { redistributeSharedCosts } from "@/lib/db/aws-client";

export async function POST(req: NextRequest) {
  const { fy_year, month_in_fy } = await req.json();
  try {
    await redistributeSharedCosts(Number(fy_year), Number(month_in_fy));
    return NextResponse.json({ ok: true });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
