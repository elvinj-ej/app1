"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter } from "next/navigation";
import { FySelector } from "@/components/aws/FySelector";
import { currentFyYear } from "@/lib/db/aws-types";
import type { WorkloadConsumption } from "@/lib/db/aws-types";
import Link from "next/link";

export default function WorkloadsPage() {
  const { user, loading, isAdmin } = useAuth();
  const router = useRouter();
  const [fyYear, setFyYear] = useState(currentFyYear());
  const [data, setData] = useState<WorkloadConsumption[]>([]);
  const [fetching, setFetching] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!loading && !user) router.push("/aws/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    setFetching(true);
    fetch(`/api/aws/monthly?fy_year=${fyYear}`)
      .then((r) => r.json())
      .then((d) => { setData(d); setFetching(false); });
  }, [fyYear, user]);

  if (loading) return null;

  const fmt = (v: number) => `$${v.toLocaleString("en-AU", { maximumFractionDigits: 0 })}`;
  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  // Aggregate by workload
  const byWorkload = new Map<number, {
    workload_id: number; name: string; owner: string | null; category: string | null;
    owner_user_id: string | null; forecast: number; invoiced: number;
    months_invoiced: number; months_total: number;
  }>();

  for (const r of data) {
    if (!isAdmin && r.owner_user_id !== user?.id) continue;
    const ex = byWorkload.get(r.workload_id) ?? {
      workload_id: r.workload_id, name: r.workload_name, owner: r.owner_name,
      category: r.category, owner_user_id: r.owner_user_id,
      forecast: 0, invoiced: 0, months_invoiced: 0, months_total: 0
    };
    ex.forecast += r.forecast_amount + r.networking_share + r.invoice_adjustment_share;
    if (r.invoiced_amount !== null) {
      ex.invoiced += r.invoiced_amount + r.networking_share + r.invoice_adjustment_share;
      ex.months_invoiced++;
    }
    ex.months_total++;
    byWorkload.set(r.workload_id, ex);
  }

  const rows = Array.from(byWorkload.values())
    .filter((r) => !search || r.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => b.forecast - a.forecast);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h1 className="text-2xl font-bold text-gray-900">Workloads — {fyLabel}</h1>
        <div className="flex gap-3 items-center">
          <input
            type="search"
            placeholder="Search workloads…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          />
          <FySelector value={fyYear} onChange={setFyYear} />
        </div>
      </div>

      {fetching ? (
        <div className="text-center text-gray-400 py-12">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="text-center text-gray-400 py-12">
          No workloads found. {isAdmin && <Link href="/aws/admin" className="text-blue-600 hover:underline">Add workloads in Admin →</Link>}
        </div>
      ) : (
        <div className="bg-white rounded-xl shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Workload</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Category</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Owner</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">FY Forecast</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">FY Invoiced</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">Coverage</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.workload_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{r.name}</td>
                  <td className="px-4 py-3 text-gray-500">{r.category ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-600">{r.owner ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono">{fmt(r.forecast)}</td>
                  <td className="px-4 py-3 text-right font-mono text-blue-700">
                    {r.months_invoiced > 0 ? fmt(r.invoiced) : <span className="text-gray-400 text-xs">Pending</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-500">
                    {r.months_invoiced}/{r.months_total} mo
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/aws/workloads/${r.workload_id}?fy=${fyYear}`} className="text-blue-600 text-xs hover:underline">
                      Details →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
