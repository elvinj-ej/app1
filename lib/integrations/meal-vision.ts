/**
 * Meal photo analysis via Claude vision API.
 * Estimates calories and macros from an uploaded food image.
 *
 * Required env var: ANTHROPIC_API_KEY
 */

import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

export interface MacroEstimate {
  calories: number;
  proteinG: number;
  carbsG: number;
  fatG: number;
  description: string;       // what Claude identified in the image
  confidenceNote: string;    // qualitative confidence / caveats
  items: FoodItem[];
}

export interface FoodItem {
  name: string;
  estimatedCalories: number;
  proteinG: number;
  carbsG: number;
  fatG: number;
}

const SYSTEM_PROMPT = `You are a registered dietitian and nutrition expert.
When shown a food photo, identify each food item and estimate its nutritional content.
Be specific about portion sizes based on visual cues (plate size, utensils, packaging).
Always respond in valid JSON matching the schema provided.`;

const USER_PROMPT = `Analyse this meal photo and estimate the nutritional content.

Respond ONLY with a JSON object matching this exact schema:
{
  "description": "brief description of what you see",
  "items": [
    {
      "name": "food item name",
      "estimatedCalories": 0,
      "proteinG": 0,
      "carbsG": 0,
      "fatG": 0
    }
  ],
  "calories": 0,
  "proteinG": 0,
  "carbsG": 0,
  "fatG": 0,
  "confidenceNote": "note about estimation accuracy / assumptions made"
}

The totals (calories, proteinG, carbsG, fatG) should be the sum of all items.
Use realistic portion estimates. If packaging is visible, use those values.`;

/**
 * Analyse a meal image from a URL.
 * For base64 images use analyseFromBase64().
 */
export async function analyseFromUrl(imageUrl: string): Promise<MacroEstimate> {
  const response = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [
      {
        role: "user",
        content: [
          { type: "image", source: { type: "url", url: imageUrl } },
          { type: "text", text: USER_PROMPT },
        ],
      },
    ],
  });

  return parseResponse(response);
}

/**
 * Analyse a meal image from base64-encoded data.
 * mediaType: "image/jpeg" | "image/png" | "image/webp" | "image/gif"
 */
export async function analyseFromBase64(
  base64Data: string,
  mediaType: "image/jpeg" | "image/png" | "image/webp" | "image/gif" = "image/jpeg"
): Promise<MacroEstimate> {
  const response = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    messages: [
      {
        role: "user",
        content: [
          {
            type: "image",
            source: { type: "base64", media_type: mediaType, data: base64Data },
          },
          { type: "text", text: USER_PROMPT },
        ],
      },
    ],
  });

  return parseResponse(response);
}

function parseResponse(response: Anthropic.Message): MacroEstimate {
  const text = response.content
    .filter((b) => b.type === "text")
    .map((b) => (b as Anthropic.TextBlock).text)
    .join("");

  // Strip markdown code fences if present
  const jsonStr = text.replace(/```(?:json)?\n?/g, "").trim();

  try {
    const parsed = JSON.parse(jsonStr);
    return {
      calories: Number(parsed.calories) || 0,
      proteinG: Number(parsed.proteinG) || 0,
      carbsG: Number(parsed.carbsG) || 0,
      fatG: Number(parsed.fatG) || 0,
      description: parsed.description ?? "",
      confidenceNote: parsed.confidenceNote ?? "",
      items: (parsed.items ?? []).map((item: Record<string, unknown>) => ({
        name: String(item.name ?? ""),
        estimatedCalories: Number(item.estimatedCalories) || 0,
        proteinG: Number(item.proteinG) || 0,
        carbsG: Number(item.carbsG) || 0,
        fatG: Number(item.fatG) || 0,
      })),
    };
  } catch {
    throw new Error(`Failed to parse Claude response as JSON:\n${text}`);
  }
}
