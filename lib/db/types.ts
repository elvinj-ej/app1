export type Json = string | number | boolean | null | { [key: string]: Json } | Json[];

export interface Database {
  public: {
    Tables: {
      profiles: {
        Row: { id: string; display_name: string | null; timezone: string; created_at: string };
        Insert: { id: string; display_name?: string | null; timezone?: string };
        Update: { display_name?: string | null; timezone?: string };
      };
      body_weight: {
        Row: {
          id: number; user_id: string; date: string;
          weight_kg: number; source: "apple_health" | "manual" | "garmin"; created_at: string;
        };
        Insert: {
          user_id: string; date: string; weight_kg: number;
          source: "apple_health" | "manual" | "garmin";
        };
        Update: { weight_kg?: number; source?: "apple_health" | "manual" | "garmin" };
      };
      garmin_daily: {
        Row: {
          id: number; user_id: string; date: string;
          total_kcal: number | null; active_kcal: number | null; bmr_kcal: number | null;
          total_steps: number | null; distance_meters: number | null;
          avg_heart_rate: number | null; synced_at: string;
        };
        Insert: {
          user_id: string; date: string;
          total_kcal?: number | null; active_kcal?: number | null; bmr_kcal?: number | null;
          total_steps?: number | null; distance_meters?: number | null;
          avg_heart_rate?: number | null;
        };
        Update: {
          total_kcal?: number | null; active_kcal?: number | null; bmr_kcal?: number | null;
          total_steps?: number | null; distance_meters?: number | null;
          avg_heart_rate?: number | null;
        };
      };
      workouts: {
        Row: {
          id: number; user_id: string; hevy_id: string; title: string | null;
          description: string | null; start_time: string; end_time: string | null;
          exercises: Json; volume_kg: number | null; total_sets: number | null;
          total_reps: number | null; synced_at: string;
        };
        Insert: {
          user_id: string; hevy_id: string; title?: string | null;
          description?: string | null; start_time: string; end_time?: string | null;
          exercises?: Json; volume_kg?: number | null; total_sets?: number | null;
          total_reps?: number | null;
        };
        Update: {
          title?: string | null; exercises?: Json; volume_kg?: number | null;
          total_sets?: number | null; total_reps?: number | null;
        };
      };
      meals: {
        Row: {
          id: number; user_id: string; logged_at: string; date: string;
          photo_url: string | null; description: string | null;
          calories: number; protein_g: number; carbs_g: number; fat_g: number;
          items: Json; confidence_note: string | null; user_corrected: boolean;
        };
        Insert: {
          user_id: string; logged_at?: string; photo_url?: string | null;
          description?: string | null; calories: number; protein_g: number;
          carbs_g: number; fat_g: number; items?: Json;
          confidence_note?: string | null; user_corrected?: boolean;
        };
        Update: {
          calories?: number; protein_g?: number; carbs_g?: number; fat_g?: number;
          items?: Json; user_corrected?: boolean;
        };
      };
    };
    Views: {
      daily_summary: {
        Row: {
          user_id: string | null; date: string | null;
          garmin_total_kcal: number | null; garmin_active_kcal: number | null;
          total_steps: number | null; weight_kg: number | null;
          weight_source: string | null; total_meal_calories: number | null;
          total_protein_g: number | null; total_carbs_g: number | null;
          total_fat_g: number | null; meal_count: number | null;
          workout_count: number | null; workout_volume_kg: number | null;
        };
      };
    };
  };
}
