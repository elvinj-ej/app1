import { Card, CardTitle } from "@/components/ui/card";
import { Dumbbell } from "lucide-react";

interface WorkoutSummaryProps {
  workoutCount: number;
  volumeKg: number;
}

export function WorkoutSummary({ workoutCount, volumeKg }: WorkoutSummaryProps) {
  return (
    <Card>
      <CardTitle>Workouts today</CardTitle>
      {workoutCount === 0 ? (
        <p className="text-sm text-gray-400 text-center py-4">Rest day 🛋️</p>
      ) : (
        <div className="flex items-center gap-4">
          <div className="bg-violet-50 p-3 rounded-xl">
            <Dumbbell className="w-6 h-6 text-violet-500" />
          </div>
          <div>
            <p className="text-2xl font-bold text-gray-800">{workoutCount} session{workoutCount > 1 ? "s" : ""}</p>
            <p className="text-sm text-gray-400">{volumeKg.toLocaleString()} kg total volume</p>
          </div>
        </div>
      )}
    </Card>
  );
}
