import { NextRequest, NextResponse } from "next/server";
import { getDailySummary, getWeightHistory, getMealsByDate } from "@/lib/db/persist";

/**
 * GET /api/dashboard?userId=<uuid>&date=YYYY-MM-DD
 * Returns everything the dashboard needs in one request.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const userId = searchParams.get("userId");
  const date = searchParams.get("date") ?? new Date().toISOString().slice(0, 10);

  if (!userId) {
    return NextResponse.json({ error: "userId is required" }, { status: 400 });
  }

  try {
    const [summary, weightHistory, meals] = await Promise.all([
      getDailySummary(userId, date),
      getWeightHistory(userId, 30),
      getMealsByDate(userId, date),
    ]);

    return NextResponse.json({ summary, weightHistory, meals, date });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
