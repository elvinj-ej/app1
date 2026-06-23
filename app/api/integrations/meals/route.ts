import { NextRequest, NextResponse } from "next/server";
import { analyseFromBase64, analyseFromUrl } from "@/lib/integrations/meal-vision";

/**
 * POST /api/integrations/meals
 *
 * Analyse a meal photo and return calorie + macro estimates.
 *
 * Accepts JSON body with either:
 *   { "imageUrl": "https://..." }           → analyse from URL
 *   { "imageBase64": "...", "mediaType": "image/jpeg" }  → analyse from upload
 *
 * Returns MacroEstimate JSON.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();

    let estimate;

    if (body.imageUrl) {
      estimate = await analyseFromUrl(body.imageUrl);
    } else if (body.imageBase64) {
      const mediaType = body.mediaType ?? "image/jpeg";
      estimate = await analyseFromBase64(body.imageBase64, mediaType);
    } else {
      return NextResponse.json(
        { error: "Provide either imageUrl or imageBase64" },
        { status: 400 }
      );
    }

    // TODO: persist meal entry + estimate to your database here
    // e.g. await db.meals.create({ ...estimate, userId, loggedAt: new Date() })

    return NextResponse.json(estimate);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
