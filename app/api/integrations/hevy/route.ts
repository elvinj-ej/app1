import { NextRequest, NextResponse } from "next/server";
import { getWorkouts, getWorkoutsSince, summariseVolume } from "@/lib/integrations/hevy";
import { upsertWorkouts } from "@/lib/db/persist";

/**
 * GET /api/integrations/hevy?page=1&pageSize=10       → paginated workouts
 * GET /api/integrations/hevy?since=YYYY-MM-DD         → all workouts since date
 * GET /api/integrations/hevy?page=1&summary=true      → workouts with volume summary
 */
export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const since = searchParams.get("since");
    const page = Number(searchParams.get("page") ?? 1);
    const pageSize = Number(searchParams.get("pageSize") ?? 10);
    const summary = searchParams.get("summary") === "true";

    if (since) {
      const workouts = await getWorkoutsSince(since);
      const userId = searchParams.get("userId");
      if (userId && workouts.length > 0) await upsertWorkouts(userId, workouts);
      const data = summary
        ? workouts.map((w) => ({ ...w, volume: summariseVolume(w) }))
        : workouts;
      return NextResponse.json({ count: data.length, data });
    }

    const result = await getWorkouts(page, pageSize);
    const data = summary
      ? result.workouts.map((w) => ({ ...w, volume: summariseVolume(w) }))
      : result.workouts;

    return NextResponse.json({
      page: result.page,
      page_count: result.page_count,
      data,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
