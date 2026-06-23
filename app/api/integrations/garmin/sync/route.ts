import { NextRequest, NextResponse } from "next/server";
import { getGarminClient } from "@/lib/integrations/garmin";
import { upsertGarminDaily, upsertBodyWeight } from "@/lib/db/persist";

/**
 * POST /api/integrations/garmin/sync
 * Body: { userId: string, startDate?: string, endDate?: string }
 *
 * Pulls Garmin data for the given date range (defaults to today)
 * and persists it. Designed to be called by a daily cron job.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { userId } = body;
    if (!userId) {
      return NextResponse.json({ error: "userId is required" }, { status: 400 });
    }

    const today = new Date().toISOString().slice(0, 10);
    const startDate: string = body.startDate ?? today;
    const endDate: string = body.endDate ?? today;

    const client = await getGarminClient();
    const [dailySummaries, weightData] = await Promise.all([
      client.getDailySummaryRange(startDate, endDate),
      client.getWeightMeasurements(startDate, endDate),
    ]);

    const [savedSummaries, savedWeights] = await Promise.all([
      upsertGarminDaily(userId, dailySummaries),
      upsertBodyWeight(
        userId,
        weightData.map((w) => ({
          date: w.date as string,
          weightKg: (w.weight as number) / 1000,
          source: "garmin" as const,
        }))
      ),
    ]);

    return NextResponse.json({
      synced: { summaries: savedSummaries?.length ?? 0, weights: savedWeights?.length ?? 0 },
      dateRange: { startDate, endDate },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
