"use client";

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import type { WorkloadConsumption } from "@/lib/db/aws-types";
import { FY_MONTH_LABELS } from "@/lib/db/aws-types";

interface Props {
  data: WorkloadConsumption[];
  showForecast?: boolean;
}

export function ConsumptionChart({ data, showForecast = true }: Props) {
  const byMonth = new Map<number, { month: string; forecast: number; invoiced: number | null; effective: number }>();

  for (const row of data) {
    const label = FY_MONTH_LABELS[row.month_in_fy];
    const existing = byMonth.get(row.month_in_fy) ?? { month: label, forecast: 0, invoiced: null, effective: 0 };
    existing.forecast += row.forecast_amount + row.networking_share + row.invoice_adjustment_share;
    if (row.invoiced_amount !== null) {
      existing.invoiced = (existing.invoiced ?? 0) + row.invoiced_amount + row.networking_share + row.invoice_adjustment_share;
    }
    existing.effective += row.effective_total;
    byMonth.set(row.month_in_fy, existing);
  }

  const chartData = Array.from(byMonth.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([, v]) => v);

  const fmtCurrency = (v: unknown) =>
    typeof v === "number" ? `$${v.toLocaleString("en-AU", { maximumFractionDigits: 0 })}` : String(v);

  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={chartData} margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="month" />
        <YAxis tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} />
        <Tooltip formatter={fmtCurrency} />
        <Legend />
        {showForecast && (
          <Bar dataKey="forecast" name="Forecast" fill="#93c5fd" radius={[2, 2, 0, 0]} />
        )}
        <Bar dataKey="invoiced" name="Invoiced" fill="#1d4ed8" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
