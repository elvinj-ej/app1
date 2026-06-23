export { supabase, getAdminClient } from "./client";
export {
  upsertBodyWeight,
  upsertGarminDaily,
  upsertWorkouts,
  insertMeal,
  updateMeal,
  getDailySummary,
  getWeightHistory,
  getMealsByDate,
} from "./persist";
export type { Database } from "./types";
