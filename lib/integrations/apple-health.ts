/**
 * Apple Health integration via webhook push.
 *
 * Since Apple Health has no web API, we receive data pushed from:
 *   - "Health Auto Export" iOS app (https://www.healthautoexport.com)
 *   - A custom iOS Shortcut
 *
 * Both send POST requests to /api/integrations/apple-health/webhook.
 *
 * Payload shape matches Health Auto Export's "REST API" export format.
 * We validate with Zod and normalise to our internal schema.
 */

import { z } from "zod";

// Health Auto Export sends metrics as an array of named data points
const MetricSampleSchema = z.object({
  date: z.string(), // ISO 8601
  qty: z.number(),
  units: z.string().optional(),
});

const MetricSchema = z.object({
  name: z.string(),
  units: z.string().optional(),
  data: z.array(MetricSampleSchema),
});

const AppleHealthPayloadSchema = z.object({
  data: z.object({
    metrics: z.array(MetricSchema),
  }),
});

export type AppleHealthPayload = z.infer<typeof AppleHealthPayloadSchema>;

export interface BodyWeightEntry {
  date: string;       // YYYY-MM-DD
  weightKg: number;
  source: "apple_health" | "manual" | "garmin";
}

export function parseAppleHealthPayload(raw: unknown): BodyWeightEntry[] {
  const parsed = AppleHealthPayloadSchema.parse(raw);
  const entries: BodyWeightEntry[] = [];

  for (const metric of parsed.data.metrics) {
    const isWeight =
      metric.name === "body_mass" ||
      metric.name === "Weight" ||
      metric.name.toLowerCase().includes("weight");

    if (!isWeight) continue;

    for (const sample of metric.data) {
      let weightKg = sample.qty;
      // Normalise from lbs if needed
      const unit = (sample.units ?? metric.units ?? "").toLowerCase();
      if (unit === "lb" || unit === "lbs" || unit === "pound") {
        weightKg = sample.qty * 0.453592;
      }

      entries.push({
        date: sample.date.slice(0, 10), // trim to YYYY-MM-DD
        weightKg: Math.round(weightKg * 100) / 100,
        source: "apple_health" as const,
      });
    }
  }

  return entries;
}

/**
 * Verify the shared secret sent with the webhook to prevent spoofing.
 * Set APPLE_HEALTH_WEBHOOK_SECRET in your env and configure the same
 * value in Health Auto Export's "Authorization" header field.
 */
export function verifyWebhookSecret(authHeader: string | null): boolean {
  const secret = process.env.APPLE_HEALTH_WEBHOOK_SECRET;
  if (!secret) return true; // secret not configured — open (dev only)
  return authHeader === `Bearer ${secret}`;
}
