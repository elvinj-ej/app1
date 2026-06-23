"use client";

import { RadialBarChart, RadialBar, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardTitle } from "@/components/ui/card";

interface MacroRingProps {
  calories: number;
  caloriesBurned: number;
  proteinG: number;
  proteinGoalG?: number;
}

export function MacroRing({ calories, caloriesBurned, proteinG, proteinGoalG = 160 }: MacroRingProps) {
  const calorieBalance = caloriesBurned - calories;
  const proteinPct = Math.min(100, Math.round((proteinG / proteinGoalG) * 100));

  const ringData = [
    { name: "Protein", value: proteinPct, fill: "#10b981" },
  ];

  return (
    <Card>
      <CardTitle>Today&apos;s Balance</CardTitle>
      <div className="flex items-center gap-6">
        {/* Radial ring for protein */}
        <div className="relative w-28 h-28 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              innerRadius="70%"
              outerRadius="100%"
              data={ringData}
              startAngle={90}
              endAngle={-270}
            >
              <RadialBar dataKey="value" cornerRadius={6} background={{ fill: "#f3f4f6" }} />
              <Tooltip formatter={(v) => [`${v}%`, "Protein goal"]} />
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-xl font-bold text-gray-800">{proteinPct}%</span>
            <span className="text-[10px] text-gray-400">protein</span>
          </div>
        </div>

        {/* Text stats */}
        <div className="flex flex-col gap-3 flex-1">
          <div>
            <p className="text-xs text-gray-400">Calorie balance</p>
            <p className={`text-2xl font-bold ${calorieBalance >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
              {calorieBalance > 0 ? "+" : ""}{calorieBalance.toLocaleString()} kcal
            </p>
            <p className="text-xs text-gray-400">{caloriesBurned} burned · {calories} eaten</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">Protein</p>
            <p className="text-lg font-semibold text-gray-700">
              {proteinG}g <span className="text-xs font-normal text-gray-400">/ {proteinGoalG}g goal</span>
            </p>
          </div>
        </div>
      </div>
    </Card>
  );
}
