import { Card, CardTitle } from "@/components/ui/card";
import Image from "next/image";

interface Meal {
  id: number;
  logged_at: string;
  photo_url: string | null;
  description: string | null;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  user_corrected: boolean;
}

interface MealListProps {
  meals: Meal[];
}

function timeLabel(iso: string) {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export function MealList({ meals }: MealListProps) {
  return (
    <Card>
      <CardTitle>Meals today</CardTitle>
      {meals.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-6">No meals logged yet.</p>
      ) : (
        <ul className="divide-y divide-gray-50 -mx-5">
          {meals.map((meal) => (
            <li key={meal.id} className="flex items-center gap-3 px-5 py-3 hover:bg-gray-50 transition">
              {/* Meal photo thumbnail */}
              <div className="w-12 h-12 rounded-xl overflow-hidden bg-gray-100 shrink-0">
                {meal.photo_url ? (
                  <Image
                    src={meal.photo_url}
                    alt={meal.description ?? "Meal"}
                    width={48}
                    height={48}
                    className="object-cover w-full h-full"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-xl">🍽️</div>
                )}
              </div>

              {/* Description */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-700 truncate">
                  {meal.description ?? "Meal"}
                  {meal.user_corrected && (
                    <span className="ml-1.5 text-[10px] text-indigo-400 font-normal">edited</span>
                  )}
                </p>
                <p className="text-xs text-gray-400">
                  {meal.protein_g}g protein · {meal.carbs_g}g carbs · {meal.fat_g}g fat
                </p>
              </div>

              {/* Calories + time */}
              <div className="text-right shrink-0">
                <p className="text-sm font-semibold text-gray-700">{meal.calories} kcal</p>
                <p className="text-xs text-gray-400">{timeLabel(meal.logged_at)}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
