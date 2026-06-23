"use client";

import { useEffect, useState, useCallback } from "react";
import { Flame, Footprints, Scale, ChevronLeft, ChevronRight } from "lucide-react";
import { StatCard } from "./StatCard";
import { MealList } from "./MealList";
import { WorkoutSummary } from "./WorkoutSummary";
import { WeightChart } from "@/components/charts/WeightChart";
import { MacroRing } from "@/components/charts/MacroRing";

interface DashboardData {
  summary: {
    garmin_total_kcal: number | null;
    garmin_active_kcal: number | null;
    total_steps: number | null;
    weight_kg: number | null;
    total_meal_calories: number | null;
    total_protein_g: number | null;
    total_carbs_g: number | null;
    total_fat_g: number | null;
    meal_count: number | null;
    workout_count: number | null;
    workout_volume_kg: number | null;
  } | null;
  weightHistory: { date: string; weight_kg: number; source: string }[];
  meals: {
    id: number;
    logged_at: string;
    photo_url: string | null;
    description: string | null;
    calories: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    user_corrected: boolean;
  }[];
  date: string;
}

// Temporary: hardcode userId until auth is added
const USER_ID = process.env.NEXT_PUBLIC_DEMO_USER_ID ?? "";

function offsetDate(base: string, days: number): string {
  const d = new Date(base + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function formatDisplayDate(dateStr: string): string {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = offsetDate(today, -1);
  if (dateStr === today) return "Today";
  if (dateStr === yesterday) return "Yesterday";
  return new Date(dateStr + "T00:00:00").toLocaleDateString("en-US", {
    weekday: "long", month: "short", day: "numeric",
  });
}

export function Dashboard() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const today = new Date().toISOString().slice(0, 10);

  const load = useCallback(async (d: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/dashboard?userId=${USER_ID}&date=${d}`);
      if (!res.ok) throw new Error(await res.text());
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(date); }, [date, load]);

  const s = data?.summary;
  const caloriesBurned = s?.garmin_total_kcal ?? 0;
  const caloriesEaten = s?.total_meal_calories ?? 0;
  const proteinG = Math.round(s?.total_protein_g ?? 0);
  const steps = s?.total_steps ?? 0;
  const weight = s?.weight_kg;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">Fitness Dashboard</h1>
          <p className="text-xs text-gray-400">Hevy · Garmin · Apple Health · Meals</p>
        </div>

        {/* Date navigator */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setDate((d) => offsetDate(d, -1))}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition"
          >
            <ChevronLeft className="w-4 h-4 text-gray-500" />
          </button>
          <span className="text-sm font-medium text-gray-700 w-28 text-center">
            {formatDisplayDate(date)}
          </span>
          <button
            onClick={() => setDate((d) => offsetDate(d, 1))}
            disabled={date >= today}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition disabled:opacity-30"
          >
            <ChevronRight className="w-4 h-4 text-gray-500" />
          </button>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-6 space-y-4">
        {error && (
          <div className="bg-rose-50 text-rose-600 text-sm rounded-xl px-4 py-3">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-20">
            <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {/* Top stat cards */}
            <div className="grid grid-cols-2 gap-3">
              <StatCard
                title="Calories burned"
                value={caloriesBurned.toLocaleString()}
                unit="kcal"
                sub="from Garmin"
                icon={Flame}
                color="bg-orange-50"
                iconColor="text-orange-500"
              />
              <StatCard
                title="Steps"
                value={steps.toLocaleString()}
                icon={Footprints}
                color="bg-sky-50"
                iconColor="text-sky-500"
              />
              <StatCard
                title="Body weight"
                value={weight ? weight.toFixed(1) : "—"}
                unit={weight ? "kg" : undefined}
                sub="from Apple Health"
                icon={Scale}
                color="bg-indigo-50"
                iconColor="text-indigo-500"
              />
              <StatCard
                title="Meals logged"
                value={s?.meal_count ?? 0}
                unit="meals"
                sub={`${caloriesEaten} kcal eaten`}
                icon={Flame}
                color="bg-emerald-50"
                iconColor="text-emerald-500"
              />
            </div>

            {/* Calorie balance + protein ring */}
            <MacroRing
              calories={caloriesEaten}
              caloriesBurned={caloriesBurned}
              proteinG={proteinG}
            />

            {/* Weight trend chart */}
            <WeightChart data={data?.weightHistory ?? []} />

            {/* Workout summary */}
            <WorkoutSummary
              workoutCount={s?.workout_count ?? 0}
              volumeKg={Math.round(s?.workout_volume_kg ?? 0)}
            />

            {/* Meal list */}
            <MealList meals={data?.meals ?? []} />
          </>
        )}
      </main>
    </div>
  );
}
