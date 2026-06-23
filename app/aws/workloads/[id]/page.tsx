"use client";

import { useEffect, useState, use } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter, useSearchParams } from "next/navigation";
import { ConsumptionChart } from "@/components/aws/ConsumptionChart";
import { FySelector } from "@/components/aws/FySelector";
import { currentFyYear, FY_MONTH_LABELS } from "@/lib/db/aws-types";
import type { WorkloadConsumption, Workload } from "@/lib/db/aws-types";
import Link from "next/link";

export default function WorkloadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, loading, isAdmin } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [fyYear, setFyYear] = useState(Number(searchParams.get("fy") ?? currentFyYear()));
  const [data, setData] = useState<WorkloadConsumption[]>([]);
  const [workload, setWorkload] = useState<Workload | null>(null);
  const [fetching, setFetching] = useState(false);
  const [editingMonth, setEditingMonth] = useState<number | null>(null);
  const [invoiceInput, setInvoiceInput] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push("/aws/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    setFetching(true);
    Promise.all([
      fetch(`/api/aws/monthly?fy_year=${fyYear}&workload_id=${id}`).then((r) => r.json()),
      fetch(`/api/aws/workloads`).then((r) => r.json()),
    ]).then(([consumption, workloads]) => {
      setData(consumption);
      const wl = workloads.find((w: Workload) => String(w.id) === id);
      setWorkload(wl ?? null);
      setFetching(false);
    });
  }, [fyYear, id, user]);

  if (loading) return null;

  const fmt = (v: number | null) =>
    v === null ? "—" : `$${v.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  const totalForecast = data.reduce(
    (s, r) => s + r.forecast_amount + r.networking_share + r.invoice_adjustment_share, 0
  );
  const totalInvoiced = data
    .filter((r) => r.invoiced_amount !== null)
    .reduce((s, r) => s + (r.invoiced_amount ?? 0) + r.networking_share + r.invoice_adjustment_share, 0);

  async function saveInvoice(monthInFy: number) {
    setSaving(true);
    await fetch("/api/aws/monthly", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workload_id: Number(id),
        fy_year: fyYear,
        month_in_fy: monthInFy,
        invoiced_amount: parseFloat(invoiceInput),
      }),
    });
    // Refresh
    const fresh = await fetch(`/api/aws/monthly?fy_year=${fyYear}&workload_id=${id}`).then((r) => r.json());
    setData(fresh);
    setEditingMonth(null);
    setSaving(false);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/aws/workloads" className="text-gray-400 hover:text-gray-600 text-sm">← Workloads</Link>
        <span className="text-gray-300">/</span>
        <h1 className="text-2xl font-bold text-gray-900">{workload?.name ?? `Workload ${id}`}</h1>
        <div className="ml-auto">
          <FySelector value={fyYear} onChange={setFyYear} />
        </div>
      </div>

      {workload && (
        <div className="bg-white rounded-xl shadow p-4 flex gap-6 text-sm flex-wrap">
          <div><span className="text-gray-500">Owner:</span> <span className="font-medium">{workload.owner_name ?? "—"}</span></div>
          <div><span className="text-gray-500">Email:</span> <span className="font-medium">{workload.owner_email ?? "—"}</span></div>
          <div><span className="text-gray-500">Category:</span> <span className="font-medium">{workload.category ?? "—"}</span></div>
          {workload.aws_account_id && <div><span className="text-gray-500">AWS Account:</span> <span className="font-mono text-xs">{workload.aws_account_id}</span></div>}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card label="FY Forecast" value={fmt(totalForecast)} />
        <Card label="FY Invoiced" value={totalInvoiced > 0 ? fmt(totalInvoiced) : "Pending"} />
        <Card label="Months Invoiced" value={`${data.filter((r) => r.invoiced_amount !== null).length} / 12`} />
        <Card label="FY" value={fyLabel} />
      </div>

      {/* Chart */}
      {!fetching && data.length > 0 && (
        <div className="bg-white rounded-xl shadow p-6">
          <h2 className="font-semibold text-gray-700 mb-4">Monthly Consumption</h2>
          <ConsumptionChart data={data} />
          <p className="text-xs text-gray-400 mt-2">
            Amounts include proportional share of shared networking and invoice adjustments.
          </p>
        </div>
      )}

      {/* Monthly breakdown table */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold text-gray-700">Monthly Breakdown</h2>
          {isAdmin && <span className="text-xs text-gray-400">Click "Set Invoice" to enter actual amounts</span>}
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Month</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">CUR Amount</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Forecast</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Networking</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Adj.</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Invoiced</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Effective</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
              const row = data.find((r) => r.month_in_fy === m);
              const isEditing = editingMonth === m;
              return (
                <tr key={m} className={row?.status === "invoiced" ? "bg-green-50" : "hover:bg-gray-50"}>
                  <td className="px-4 py-2.5 font-medium text-gray-800">{FY_MONTH_LABELS[m]}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-gray-500">{fmt(row?.cur_amount ?? null)}</td>
                  <td className="px-4 py-2.5 text-right font-mono">{fmt(row?.forecast_amount ?? null)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-gray-500">{fmt(row?.networking_share ?? null)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-gray-500">{fmt(row?.invoice_adjustment_share ?? null)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-blue-700">
                    {isEditing ? (
                      <input
                        type="number"
                        step="0.01"
                        value={invoiceInput}
                        onChange={(e) => setInvoiceInput(e.target.value)}
                        className="w-28 border rounded px-2 py-0.5 text-right text-sm"
                        autoFocus
                      />
                    ) : fmt(row?.invoiced_amount ?? null)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono font-semibold">{fmt(row?.effective_total ?? null)}</td>
                  <td className="px-4 py-2.5 text-right">
                    {isAdmin && (
                      isEditing ? (
                        <div className="flex gap-1 justify-end">
                          <button
                            onClick={() => saveInvoice(m)}
                            disabled={saving}
                            className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded hover:bg-blue-700 disabled:opacity-50"
                          >
                            Save
                          </button>
                          <button
                            onClick={() => setEditingMonth(null)}
                            className="text-xs text-gray-500 hover:text-gray-700"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => {
                            setInvoiceInput(String(row?.invoiced_amount ?? ""));
                            setEditingMonth(m);
                          }}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          {row?.invoiced_amount !== null && row?.invoiced_amount !== undefined ? "Edit" : "Set Invoice"}
                        </button>
                      )
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-xl shadow p-4">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p className="text-xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  );
}
