/**
 * Persistence helpers — called from API routes to save integration data.
 * All functions use the admin client (service role) since they run server-side.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

import { getAdminClient } from "./client";
import type { BodyWeightEntry } from "@/lib/integrations/apple-health";
import type { GarminDailySummary } from "@/lib/integrations/garmin";
import type { HevyWorkout } from "@/lib/integrations/hevy";
import type { MacroEstimate } from "@/lib/integrations/meal-vision";
import { summariseVolume } from "@/lib/integrations/hevy";

// ── Body Weight ───────────────────────────────────────────────

export async function upsertBodyWeight(userId: string, entries: BodyWeightEntry[]) {
  if (!entries.length) return [];
  const db = getAdminClient();
  const rows: Row[] = entries.map((e) => ({
    user_id: userId,
    date: e.date,
    weight_kg: e.weightKg,
    source: e.source,
  }));
  const { data, error } = await db
    .from("body_weight")
    .upsert(rows, { onConflict: "user_id,date,source" })
    .select();
  if (error) throw new Error(`upsertBodyWeight: ${error.message}`);
  return data ?? [];
}

// ── Garmin Daily Summaries ────────────────────────────────────

export async function upsertGarminDaily(
  userId: string,
  summaries: GarminDailySummary | GarminDailySummary[]
) {
  const list = Array.isArray(summaries) ? summaries : [summaries];
  if (!list.length) return [];
  const db = getAdminClient();
  const rows: Row[] = list.map((s) => ({
    user_id: userId,
    date: s.calendarDate,
    total_kcal: s.totalKilocalories ?? null,
    active_kcal: s.activeKilocalories ?? null,
    bmr_kcal: s.bmrKilocalories ?? null,
    total_steps: s.totalSteps ?? null,
    distance_meters: s.totalDistanceMeters ?? null,
    avg_heart_rate: s.averageHeartRateInBeatsPerMinute ?? null,
  }));
  const { data, error } = await db
    .from("garmin_daily")
    .upsert(rows, { onConflict: "user_id,date" })
    .select();
  if (error) throw new Error(`upsertGarminDaily: ${error.message}`);
  return data ?? [];
}

// ── Hevy Workouts ─────────────────────────────────────────────

export async function upsertWorkouts(userId: string, workouts: HevyWorkout[]) {
  if (!workouts.length) return [];
  const db = getAdminClient();
  const rows: Row[] = workouts.map((w) => {
    const vol = summariseVolume(w);
    return {
      user_id: userId,
      hevy_id: w.id,
      title: w.title ?? null,
      description: w.description ?? null,
      start_time: w.start_time,
      end_time: w.end_time ?? null,
      exercises: w.exercises,
      volume_kg: vol.totalVolumeKg,
      total_sets: vol.totalSets,
      total_reps: vol.totalReps,
    };
  });
  const { data, error } = await db
    .from("workouts")
    .upsert(rows, { onConflict: "user_id,hevy_id" })
    .select();
  if (error) throw new Error(`upsertWorkouts: ${error.message}`);
  return data ?? [];
}

// ── Meals ─────────────────────────────────────────────────────

export async function insertMeal(
  userId: string,
  estimate: MacroEstimate,
  photoUrl?: string
) {
  const db = getAdminClient();
  const row: Row = {
    user_id: userId,
    photo_url: photoUrl ?? null,
    description: estimate.description,
    calories: Math.round(estimate.calories),
    protein_g: estimate.proteinG,
    carbs_g: estimate.carbsG,
    fat_g: estimate.fatG,
    items: estimate.items,
    confidence_note: estimate.confidenceNote,
  };
  const { data, error } = await db.from("meals").insert(row).select().single();
  if (error) throw new Error(`insertMeal: ${error.message}`);
  return data;
}

export async function updateMeal(
  mealId: number,
  updates: { calories?: number; protein_g?: number; carbs_g?: number; fat_g?: number }
) {
  const db = getAdminClient();
  const { data, error } = await db
    .from("meals")
    .update({ ...updates, user_corrected: true })
    .eq("id", mealId)
    .select()
    .single();
  if (error) throw new Error(`updateMeal: ${error.message}`);
  return data;
}

// ── Queries ───────────────────────────────────────────────────

export async function getDailySummary(userId: string, date: string) {
  const db = getAdminClient();
  const { data, error } = await db
    .from("daily_summary")
    .select("*")
    .eq("user_id", userId)
    .eq("date", date)
    .maybeSingle();
  if (error) throw new Error(`getDailySummary: ${error.message}`);
  return data;
}

export async function getWeightHistory(userId: string, days = 30) {
  const db = getAdminClient();
  const since = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 10);
  const { data, error } = await db
    .from("body_weight")
    .select("date, weight_kg, source")
    .eq("user_id", userId)
    .gte("date", since)
    .order("date", { ascending: true });
  if (error) throw new Error(`getWeightHistory: ${error.message}`);
  return data ?? [];
}

export async function getMealsByDate(userId: string, date: string) {
  const db = getAdminClient();
  const { data, error } = await db
    .from("meals")
    .select("*")
    .eq("user_id", userId)
    .eq("date", date)
    .order("logged_at", { ascending: true });
  if (error) throw new Error(`getMealsByDate: ${error.message}`);
  return data ?? [];
}
