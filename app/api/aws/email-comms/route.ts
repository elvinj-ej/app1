import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.json();
  const { fy_label, quarter_label } = body;

  // Placeholder: in production, integrate with an email service (e.g. Resend, SES)
  // to fetch workload owners from Supabase and send per-owner consumption summaries.
  return NextResponse.json({
    message: `Emails queued for ${quarter_label} ${fy_label}. (Email service not yet configured — connect an SMTP or transactional email provider to activate.)`,
  });
}
