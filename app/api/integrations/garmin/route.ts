import { NextRequest, NextResponse } from "next/server";
import { getGarminClient } from "@/lib/integrations/garmin";

/** GET /api/integrations/garmin?date=YYYY-MM-DD  → daily summary */
/** GET /api/integrations/garmin?start=YYYY-MM-DD&end=YYYY-MM-DD  → range */
export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const date = searchParams.get("date");
    const start = searchParams.get("start");
    const end = searchParams.get("end");
    const type = searchParams.get("type") ?? "calories"; // "calories" | "weight"

    const client = await getGarminClient();

    if (type === "weight") {
      const startDate = start ?? date ?? new Date().toISOString().slice(0, 10);
      const endDate = end ?? startDate;
      const data = await client.getWeightMeasurements(startDate, endDate);
      return NextResponse.json({ data });
    }

    if (start && end) {
      const data = await client.getDailySummaryRange(start, end);
      return NextResponse.json({ data });
    }

    const targetDate = date ?? new Date().toISOString().slice(0, 10);
    const data = await client.getDailySummary(targetDate);
    return NextResponse.json({ data });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
