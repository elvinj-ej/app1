"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter } from "next/navigation";
import { FySelector } from "@/components/aws/FySelector";
import { ConsumptionChart } from "@/components/aws/ConsumptionChart";
import { TopBar } from "@/components/aws/TopBar";
import { currentFyYear, FY_MONTH_LABELS } from "@/lib/db/aws-types";
import type { WorkloadConsumption } from "@/lib/db/aws-types";
import Link from "next/link";

export default function DashboardPage() {
  const { user, profile, loading, isAdmin } = useAuth();
  const router = useRouter();
  const [fyYear, setFyYear] = useState(currentFyYear());
  const [data, setData] = useState<WorkloadConsumption[]>([]);
  const [fetching, setFetching] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push("/aws/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    setFetching(true);
    const url = isAdmin
      ? `/api/aws/monthly?fy_year=${fyYear}`
      : `/api/aws/monthly?fy_year=${fyYear}`;
    fetch(url)
      .then((r) => r.json())
      .then((d) => { setData(d); setFetching(false); });
  }, [fyYear, user, isAdmin]);

  if (loading) return <div className="text-gray-500 mt-20 text-center">Loading…</div>;

  // Summary stats
  const totalForecast = data.reduce(
    (s, r) => s + r.forecast_amount + r.networking_share + r.invoice_adjustment_share, 0
  );
  const invoicedRows = data.filter((r) => r.invoiced_amount !== null);
  const totalInvoiced = invoicedRows.reduce(
    (s, r) => s + (r.invoiced_amount ?? 0) + r.networking_share + r.invoice_adjustment_share, 0
  );

  // Group by workload for summary table
  const byWorkload = new Map<number, {
    name: string; category: string | null; owner: string | null;
    forecast: number; invoiced: number; months_invoiced: number;
    workload_id: number; owner_user_id: string | null;
  }>();

  for (const r of data) {
    const ex = byWorkload.get(r.workload_id) ?? {
      name: r.workload_name, category: r.category, owner: r.owner_name,
      forecast: 0, invoiced: 0, months_invoiced: 0,
      workload_id: r.workload_id, owner_user_id: r.owner_user_id
    };
    ex.forecast += r.forecast_amount + r.networking_share + r.invoice_adjustment_share;
    if (r.invoiced_amount !== null) {
      ex.invoiced += r.invoiced_amount + r.networking_share + r.invoice_adjustment_share;
      ex.months_invoiced++;
    }
    byWorkload.set(r.workload_id, ex);
  }

  // For non-admins, filter to own workloads only
  const rows = Array.from(byWorkload.values())
    .filter((r) => isAdmin || r.owner_user_id === user?.id)
    .sort((a, b) => b.forecast - a.forecast);

  const fmt = (v: number) => `$${v.toLocaleString("en-AU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  return (
    <div className="flex flex-col min-h-screen">
      <TopBar fyLabel={fyLabel} fySelector={<FySelector value={fyYear} onChange={setFyYear} />} />
      <div className="flex-1 p-8 space-y-6">

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label={`${fyLabel} Forecast (YTD)`} value={fmt(totalForecast)} color="blue" />
        <StatCard label={`${fyLabel} Invoiced (YTD)`} value={fmt(totalInvoiced)} color="green" />
        <StatCard label="Months Invoiced" value={`${new Set(invoicedRows.map((r) => r.month_in_fy)).size} / 12`} color="gray" />
      </div>

      {/* Chart */}
      {fetching ? (
        <div className="bg-white rounded-xl shadow p-6 text-center text-gray-400">Loading chart…</div>
      ) : data.length > 0 ? (
        <div className="bg-white rounded-xl shadow p-6">
          <h2 className="font-semibold text-gray-700 mb-4">Monthly Consumption — {fyLabel}</h2>
          <ConsumptionChart data={rows.flatMap((r) => data.filter((d) => d.workload_id === r.workload_id))} />
          <p className="text-xs text-gray-400 mt-2">
            Blue bars = Forecast (incl. networking + adjustments). Dark bars = Invoiced (actual from Telstra).
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow p-8 text-center text-gray-400">
          No data for {fyLabel}. {isAdmin && <Link href="/aws/admin" className="text-blue-600 hover:underline">Set up workloads and forecasts →</Link>}
        </div>
      )}

      {/* Workloads table */}
      {rows.length > 0 && (
        <div className="bg-white rounded-xl shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Workload</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Owner</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Category</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">FY Forecast</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">FY Invoiced</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.workload_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{r.name}</td>
                  <td className="px-4 py-3 text-gray-600">{r.owner ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-500">{r.category ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmt(r.forecast)}</td>
                  <td className="px-4 py-3 text-right font-mono text-blue-700">
                    {r.months_invoiced > 0 ? fmt(r.invoiced) : <span className="text-gray-400 text-xs">Pending</span>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/aws/workloads/${r.workload_id}?fy=${fyYear}`} className="text-blue-600 text-xs hover:underline">
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  const colors: Record<string, string> = {
    blue: "border-blue-200 bg-blue-50",
    green: "border-green-200 bg-green-50",
    gray: "border-gray-200 bg-gray-50",
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  );
}
