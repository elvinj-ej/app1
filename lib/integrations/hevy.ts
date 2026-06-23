/**
 * Hevy workout tracker integration.
 *
 * Hevy exposes an official API at https://api.hevyapp.com (v1).
 * Docs: https://api.hevyapp.com/docs
 *
 * Required env var: HEVY_API_KEY
 * Obtain from: Hevy app → Settings → API (requires Hevy Pro)
 */

import axios from "axios";

const BASE_URL = "https://api.hevyapp.com/v1";

function hevyClient() {
  const apiKey = process.env.HEVY_API_KEY;
  if (!apiKey) throw new Error("HEVY_API_KEY must be set");
  return axios.create({
    baseURL: BASE_URL,
    headers: { "api-key": apiKey, "Content-Type": "application/json" },
  });
}

export interface HevySet {
  type: string;           // "normal" | "warmup" | "dropset" etc.
  weight_kg: number | null;
  reps: number | null;
  rpe: number | null;
}

export interface HevyExercise {
  title: string;
  notes: string;
  sets: HevySet[];
}

export interface HevyWorkout {
  id: string;
  title: string;
  description: string;
  start_time: string;   // ISO 8601
  end_time: string;
  exercises: HevyExercise[];
}

export interface HevyWorkoutPage {
  page: number;
  page_count: number;
  workouts: HevyWorkout[];
}

/** Fetch a page of recent workouts (newest first). */
export async function getWorkouts(
  page = 1,
  pageSize = 10
): Promise<HevyWorkoutPage> {
  const client = hevyClient();
  const resp = await client.get("/workouts", {
    params: { page, pageSize },
  });
  return resp.data;
}

/** Fetch all workouts since a given date (handles pagination). */
export async function getWorkoutsSince(sinceDate: string): Promise<HevyWorkout[]> {
  const client = hevyClient();
  const since = new Date(sinceDate).getTime();
  const results: HevyWorkout[] = [];
  let page = 1;
  let hasMore = true;

  while (hasMore) {
    const resp = await client.get("/workouts", { params: { page, pageSize: 10 } });
    const data: HevyWorkoutPage = resp.data;

    for (const workout of data.workouts) {
      if (new Date(workout.start_time).getTime() >= since) {
        results.push(workout);
      }
    }

    // Workouts are newest-first; stop when we pass our target date
    const oldest = data.workouts.at(-1);
    if (!oldest || new Date(oldest.start_time).getTime() < since) {
      hasMore = false;
    } else {
      hasMore = page < data.page_count;
      page++;
    }
  }

  return results;
}

/** Summarise total volume (sets × reps × weight) per workout. */
export function summariseVolume(workout: HevyWorkout) {
  let totalVolumeKg = 0;
  let totalSets = 0;
  let totalReps = 0;

  for (const exercise of workout.exercises) {
    for (const set of exercise.sets) {
      if (set.type === "warmup") continue;
      totalSets++;
      if (set.weight_kg && set.reps) {
        totalVolumeKg += set.weight_kg * set.reps;
        totalReps += set.reps;
      }
    }
  }

  return { totalVolumeKg, totalSets, totalReps };
}
