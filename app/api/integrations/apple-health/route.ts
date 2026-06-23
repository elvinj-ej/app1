import { NextRequest, NextResponse } from "next/server";
import {
  parseAppleHealthPayload,
  verifyWebhookSecret,
} from "@/lib/integrations/apple-health";
import { upsertBodyWeight } from "@/lib/db/persist";

/**
 * POST /api/integrations/apple-health
 *
 * Webhook endpoint for Health Auto Export (iOS app) or custom Shortcuts.
 *
 * Health Auto Export setup:
 *   1. Install the app on your iPhone
 *   2. Settings → Automation → REST API
 *   3. URL: https://your-domain/api/integrations/apple-health
 *   4. Method: POST
 *   5. Authorization: Bearer <APPLE_HEALTH_WEBHOOK_SECRET>
 *   6. Select metrics: Body Mass (Weight)
 */
export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("authorization");

  if (!verifyWebhookSecret(authHeader)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const body = await req.json();
    const entries = parseAppleHealthPayload(body);

    // userId comes from a query param or auth header in production
    // For now we require ?userId=<uuid> on the webhook URL
    const userId = new URL(req.url).searchParams.get("userId");
    if (userId) {
      await upsertBodyWeight(userId, entries);
    }

    return NextResponse.json({
      received: entries.length,
      entries,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Parse error";
    return NextResponse.json({ error: message }, { status: 400 });
  }
}
