"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Card, CardTitle } from "@/components/ui/card";

interface WeightPoint {
  date: string;
  weight_kg: number;
  source: string;
}

interface WeightChartProps {
  data: WeightPoint[];
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function WeightChart({ data }: WeightChartProps) {
  if (!data.length) {
    return (
      <Card>
        <CardTitle>Body Weight — 30 days</CardTitle>
        <p className="text-sm text-gray-400 text-center py-8">No weight data yet.</p>
      </Card>
    );
  }

  const min = Math.min(...data.map((d) => d.weight_kg));
  const max = Math.max(...data.map((d) => d.weight_kg));
  const pad = 1;

  const chartData = data.map((d) => ({
    date: formatDate(d.date),
    weight: d.weight_kg,
  }));

  return (
    <Card>
      <CardTitle>Body Weight — 30 days</CardTitle>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "#9ca3af" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[min - pad, max + pad]}
            tick={{ fontSize: 11, fill: "#9ca3af" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}kg`}
          />
          <Tooltip
            formatter={(v) => [`${v} kg`, "Weight"]}
            contentStyle={{ borderRadius: 10, border: "none", boxShadow: "0 2px 8px rgba(0,0,0,0.1)" }}
          />
          <Line
            type="monotone"
            dataKey="weight"
            stroke="#6366f1"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 4, fill: "#6366f1" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}
