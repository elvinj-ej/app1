import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  // Just redirect to login — we handle auth client-side
  return NextResponse.redirect(new URL("/aws/login", url.origin));
}
