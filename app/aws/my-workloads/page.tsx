"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/aws/TopBar";
import { currentFyYear, FY_MONTH_LABELS } from "@/lib/db/aws-types";
import type { WorkloadConsumption } from "@/lib/db/aws-types";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";

export default function MyWorkloadsPage() {
  const { user, profile, loading } = useAuth();
  const router = useRouter();
  const fyYear = currentFyYear();
  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  const [data, setData] = useState<WorkloadConsumption[]>([]);
  const [fetching, setFetching] = useState(true);
  const [selectedWorkload, setSelectedWorkload] = useState<number | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/aws/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    fetch(`/api/aws/monthly?fy_year=${fyYear}`)
      .then((r) => r.json())
      .then((d: WorkloadConsumption[]) => {
        const rows = Array.isArray(d) ? d : [];
        setData(rows);
        // Auto-select first workload
        const ids = [...new Set(rows.map((r) => r.workload_id))];
        if (ids.length > 0) setSelectedWorkload(ids[0]);
        setFetching(false);
      });
  }, [user, fyYear]);

  if (loading) return null;

  const fmt = (v: number) => `$${v.toLocaleString("en-AU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  // Get unique workloads
  const workloadMap = new Map<number, { id: number; name: string }>();
  for (const r of data) {
    if (!workloadMap.has(r.workload_id)) workloadMap.set(r.workload_id, { id: r.workload_id, name: r.workload_name });
  }
  const workloads = Array.from(workloadMap.values());

  // Data for selected workload across last 12 months + 2 forecast
  const selected = data.filter((r) => r.workload_id === selectedWorkload)
    .sort((a, b) => a.month_in_fy - b.month_in_fy);

  // Build chart data: 12 historical + 2 upcoming forecast months
  const chartData = selected.map((r) => ({
    label: FY_MONTH_LABELS[r.month_in_fy as keyof typeof FY_MONTH_LABELS],
    month: r.month_in_fy,
    forecast: r.forecast_amount + r.networking_share + r.invoice_adjustment_share,
    invoiced: r.invoiced_amount !== null ? r.invoiced_amount + r.networking_share + r.invoice_adjustment_share : null,
    effective: r.effective_total,
    is_forecast: r.invoiced_amount === null,
  }));

  const selectedName = workloads.find((w) => w.id === selectedWorkload)?.name ?? "";
  const ytdTotal = chartData.reduce((s, r) => s + r.effective, 0);
  const invoicedMonths = chartData.filter((r) => !r.is_forecast).length;
  const forecastMonths = chartData.filter((r) => r.is_forecast).length;

  return (
    <div className="flex flex-col min-h-screen">
      <TopBar />
      <main className="flex-1 p-8 space-y-6">

        {/* Greeting */}
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Welcome back{profile?.email ? `, ${profile.email.split("@")[0]}` : ""}
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">Your AWS workload consumption for {fyLabel} (Jul {fyYear} – Jun {fyYear + 1})</p>
          </div>
        </div>

        {fetching ? (
          <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">Loading your data…</div>
        ) : workloads.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
            <p className="text-gray-500 text-sm">No workloads assigned to your account yet.</p>
            <p className="text-gray-400 text-xs mt-1">Contact your Cloud Platform Admin to be assigned to workloads.</p>
          </div>
        ) : (
          <>
            {/* Workload selector (if multiple) */}
            {workloads.length > 1 && (
              <div className="flex gap-2 flex-wrap">
                {workloads.map((w) => (
                  <button
                    key={w.id}
                    onClick={() => setSelectedWorkload(w.id)}
                    className={`px-3.5 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                      selectedWorkload === w.id
                        ? "bg-blue-600 text-white"
                        : "bg-white border border-gray-200 text-gray-600 hover:border-blue-300"
                    }`}
                  >
                    {w.name}
                  </button>
                ))}
              </div>
            )}

            {/* Summary cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <SummaryCard
                label={`${fyLabel} Total (YTD)`}
                value={fmt(ytdTotal)}
                sub="incl. networking allocation"
                color="blue"
              />
              <SummaryCard
                label="Invoiced Months"
                value={`${invoicedMonths}`}
                sub={`of ${invoicedMonths + forecastMonths} months in FY`}
                color="green"
              />
              <SummaryCard
                label="Forecast Months"
                value={`${forecastMonths}`}
                sub="awaiting Telstra invoice"
                color="amber"
              />
            </div>

            {/* Chart */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h3 className="text-base font-semibold text-gray-900">{selectedName}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">Monthly consumption — {fyLabel}</p>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-blue-600 inline-block" />Invoiced</span>
                  <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-blue-200 inline-block" />Forecast</span>
                </div>
              </div>

              {chartData.length === 0 ? (
                <div className="h-48 flex items-center justify-center text-gray-400 text-sm">No data yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={chartData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "#9ca3af" }} axisLine={false} tickLine={false}
                      tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} width={52} />
                    <Tooltip
                      formatter={(v: unknown) => (typeof v === "number" ? fmt(v) : String(v)) as string}
                      contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e5e7eb" }}
                      cursor={{ fill: "#f9fafb" }}
                    />
                    <Bar dataKey="effective" radius={[4, 4, 0, 0]} maxBarSize={48} name="Amount">
                      {chartData.map((entry, i) => (
                        <Cell key={i} fill={entry.is_forecast ? "#bfdbfe" : "#2563eb"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Monthly breakdown table */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <div className="px-6 py-5 border-b border-gray-100">
                <h3 className="text-base font-semibold text-gray-900">Monthly Breakdown — {selectedName}</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="text-left px-6 py-3 font-medium text-gray-600">Month</th>
                      <th className="text-right px-6 py-3 font-medium text-gray-600">Forecast</th>
                      <th className="text-right px-6 py-3 font-medium text-gray-600">Invoiced</th>
                      <th className="text-right px-6 py-3 font-medium text-gray-600">Networking Alloc.</th>
                      <th className="text-right px-6 py-3 font-medium text-gray-600">Total</th>
                      <th className="text-left px-6 py-3 font-medium text-gray-600">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {selected.map((r) => (
                      <tr key={r.month_in_fy} className="hover:bg-gray-50/50">
                        <td className="px-6 py-3 font-medium text-gray-900">
                          {FY_MONTH_LABELS[r.month_in_fy as keyof typeof FY_MONTH_LABELS]} {r.calendar_year}
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-gray-600">{fmt(r.forecast_amount)}</td>
                        <td className="px-6 py-3 text-right font-mono">
                          {r.invoiced_amount !== null
                            ? <span className="text-blue-700">{fmt(r.invoiced_amount)}</span>
                            : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="px-6 py-3 text-right font-mono text-gray-500">{fmt(r.networking_share + r.invoice_adjustment_share)}</td>
                        <td className="px-6 py-3 text-right font-mono font-semibold text-gray-900">{fmt(r.effective_total)}</td>
                        <td className="px-6 py-3">
                          {r.invoiced_amount !== null ? (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full">
                              Invoiced
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
                              Forecast
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot className="bg-gray-50 border-t border-gray-200">
                    <tr>
                      <td className="px-6 py-3 font-semibold text-gray-700">Total</td>
                      <td className="px-6 py-3 text-right font-mono font-semibold text-gray-700">
                        {fmt(selected.reduce((s, r) => s + r.forecast_amount, 0))}
                      </td>
                      <td className="px-6 py-3 text-right font-mono font-semibold text-blue-700">
                        {fmt(selected.filter((r) => r.invoiced_amount !== null).reduce((s, r) => s + (r.invoiced_amount ?? 0), 0))}
                      </td>
                      <td className="px-6 py-3 text-right font-mono font-semibold text-gray-500">
                        {fmt(selected.reduce((s, r) => s + r.networking_share + r.invoice_adjustment_share, 0))}
                      </td>
                      <td className="px-6 py-3 text-right font-mono font-semibold text-gray-900">
                        {fmt(ytdTotal)}
                      </td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function SummaryCard({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  const colors: Record<string, string> = {
    blue: "border-blue-100 bg-blue-50",
    green: "border-green-100 bg-green-50",
    amber: "border-amber-100 bg-amber-50",
  };
  return (
    <div className={`rounded-xl border p-5 ${colors[color]}`}>
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      <p className="text-xs text-gray-500 mt-1">{sub}</p>
    </div>
  );
}
