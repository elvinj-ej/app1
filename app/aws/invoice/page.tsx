"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/aws/TopBar";
import { currentFyYear, FY_MONTH_LABELS } from "@/lib/db/aws-types";
import type { WorkloadConsumption } from "@/lib/db/aws-types";

const QUARTERS = [
  { label: "Q1 (Jul–Sep)", months: [1, 2, 3] },
  { label: "Q2 (Oct–Dec)", months: [4, 5, 6] },
  { label: "Q3 (Jan–Mar)", months: [7, 8, 9] },
  { label: "Q4 (Apr–Jun)", months: [10, 11, 12] },
];

function currentQuarter() {
  const m = new Date().getMonth() + 1; // 1-12
  // FY month: Jul=1 ... Jun=12
  const fyM = m >= 7 ? m - 6 : m + 6;
  return QUARTERS.findIndex((q) => q.months.includes(fyM));
}

export default function InvoicePage() {
  const { user, loading, isAdmin } = useAuth();
  const router = useRouter();
  const fyYear = currentFyYear();
  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  const [data, setData] = useState<WorkloadConsumption[]>([]);
  const [fetching, setFetching] = useState(true);
  const [selectedQuarter, setSelectedQuarter] = useState(Math.max(0, currentQuarter()));

  // Invoice adjustment state: month_in_fy → amount
  const [adjustments, setAdjustments] = useState<Record<number, string>>({});
  const [savingAdj, setSavingAdj] = useState<Record<number, boolean>>({});

  // Email modal
  const [emailModal, setEmailModal] = useState(false);
  const [emailQuarter, setEmailQuarter] = useState(selectedQuarter);
  const [sending, setSending] = useState(false);
  const [emailResult, setEmailResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    if (!loading && !user) router.push("/aws/login");
    if (!loading && !isAdmin) router.push("/aws/dashboard");
  }, [loading, user, isAdmin, router]);

  useEffect(() => {
    if (!user || !isAdmin) return;
    fetch(`/api/aws/monthly?fy_year=${fyYear}`)
      .then((r) => r.json())
      .then((d: WorkloadConsumption[]) => { setData(Array.isArray(d) ? d : []); setFetching(false); });
  }, [user, isAdmin, fyYear]);

  // Load existing invoice adjustments
  useEffect(() => {
    if (!user || !isAdmin) return;
    fetch(`/api/aws/invoice-adjustment?fy_year=${fyYear}`)
      .then((r) => r.json())
      .then((rows: { month_in_fy: number; amount: number }[]) => {
        if (!Array.isArray(rows)) return;
        const map: Record<number, string> = {};
        rows.forEach((r) => { map[r.month_in_fy] = String(r.amount); });
        setAdjustments(map);
      });
  }, [user, isAdmin, fyYear]);

  if (loading || !isAdmin) return null;

  const fmt = (v: number) => `$${v.toLocaleString("en-AU", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

  const quarterMonths = QUARTERS[selectedQuarter].months;

  // Aggregate per workload for selected quarter
  const byWorkload = new Map<number, {
    id: number; name: string; owner: string | null; owner_user_id: string | null;
    months: { month: number; forecast: number; invoiced: number | null; effective: number }[];
  }>();

  for (const r of data) {
    if (!quarterMonths.includes(r.month_in_fy)) continue;
    const ex = byWorkload.get(r.workload_id) ?? {
      id: r.workload_id, name: r.workload_name, owner: r.owner_name, owner_user_id: r.owner_user_id,
      months: []
    };
    ex.months.push({
      month: r.month_in_fy,
      forecast: r.forecast_amount + r.networking_share + r.invoice_adjustment_share,
      invoiced: r.invoiced_amount !== null ? r.invoiced_amount + r.networking_share + r.invoice_adjustment_share : null,
      effective: r.effective_total,
    });
    byWorkload.set(r.workload_id, ex);
  }

  const workloads = Array.from(byWorkload.values()).sort((a, b) => a.name.localeCompare(b.name));

  async function saveAdjustment(month: number) {
    const amount = parseFloat(adjustments[month] ?? "0");
    if (isNaN(amount)) return;
    setSavingAdj((s) => ({ ...s, [month]: true }));
    await fetch("/api/aws/invoice-adjustment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fy_year: fyYear, month_in_fy: month, amount }),
    });
    // Trigger redistribute
    await fetch("/api/aws/redistribute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fy_year: fyYear, month_in_fy: month }),
    });
    setSavingAdj((s) => ({ ...s, [month]: false }));
    // Refresh data
    const d = await fetch(`/api/aws/monthly?fy_year=${fyYear}`).then((r) => r.json());
    setData(Array.isArray(d) ? d : []);
  }

  async function sendEmails() {
    setSending(true);
    setEmailResult(null);
    const qMonths = QUARTERS[emailQuarter].months;
    // Gather unique owners + their quarter totals
    const ownerMap = new Map<string, { name: string; email: string | null; workloads: { name: string; total: number }[] }>();
    for (const w of workloads) {
      if (!w.owner_user_id) continue;
      const qTotal = w.months
        .filter((m) => qMonths.includes(m.month))
        .reduce((s, m) => s + m.effective, 0);
      const ex = ownerMap.get(w.owner_user_id) ?? { name: w.owner ?? "Owner", email: null, workloads: [] };
      ex.workloads.push({ name: w.name, total: qTotal });
      ownerMap.set(w.owner_user_id, ex);
    }

    // Call email API
    const res = await fetch("/api/aws/email-comms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fy_year: fyYear,
        quarter: emailQuarter,
        quarter_label: QUARTERS[emailQuarter].label,
        fy_label: fyLabel,
      }),
    });
    const json = await res.json();
    setSending(false);
    setEmailResult({ ok: res.ok, message: json.message ?? (res.ok ? "Emails queued." : "Failed to send.") });
  }

  return (
    <div className="flex flex-col min-h-screen">
      <TopBar />
      <main className="flex-1 p-8 space-y-6 max-w-6xl">

        {/* Quarter selector + Send email button */}
        <div className="flex items-center justify-between">
          <div className="flex gap-2">
            {QUARTERS.map((q, i) => (
              <button
                key={q.label}
                onClick={() => setSelectedQuarter(i)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  selectedQuarter === i
                    ? "bg-blue-600 text-white"
                    : "bg-white border border-gray-200 text-gray-600 hover:border-blue-300 hover:text-blue-700"
                }`}
              >
                {q.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => { setEmailQuarter(selectedQuarter); setEmailModal(true); setEmailResult(null); }}
            className="flex items-center gap-2 bg-white border border-gray-200 hover:border-blue-300 hover:text-blue-700 text-gray-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors shadow-sm"
          >
            <MailIcon className="w-4 h-4" />
            Notify Workload Owners
          </button>
        </div>

        {/* Invoice adjustments (Row 16 values) */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Invoice Adjustments</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Enter the Row 16 Telstra invoice difference per month. These are distributed proportionally across workloads.
            </p>
          </div>
          <div className="px-6 py-4 grid grid-cols-3 gap-4">
            {quarterMonths.map((m) => (
              <div key={m} className="space-y-1.5">
                <label className="text-xs font-medium text-gray-600">{FY_MONTH_LABELS[m as keyof typeof FY_MONTH_LABELS]}</label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                    <input
                      type="number"
                      step="0.01"
                      value={adjustments[m] ?? ""}
                      onChange={(e) => setAdjustments((a) => ({ ...a, [m]: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg pl-7 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="0.00"
                    />
                  </div>
                  <button
                    onClick={() => saveAdjustment(m)}
                    disabled={savingAdj[m]}
                    className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
                  >
                    {savingAdj[m] ? "…" : "Save"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Workload consumption table */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">
              {QUARTERS[selectedQuarter].label} — {fyLabel} Consumption
            </h2>
          </div>
          {fetching ? (
            <div className="px-6 py-10 text-center text-gray-400 text-sm">Loading…</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="text-left px-6 py-3 font-medium text-gray-600">Workload</th>
                    <th className="text-left px-6 py-3 font-medium text-gray-600">Owner</th>
                    {quarterMonths.map((m) => (
                      <th key={m} className="text-right px-4 py-3 font-medium text-gray-600">
                        {FY_MONTH_LABELS[m as keyof typeof FY_MONTH_LABELS]}
                      </th>
                    ))}
                    <th className="text-right px-6 py-3 font-medium text-gray-600">Q Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {workloads.map((w) => {
                    const qTotal = w.months.reduce((s, m) => s + m.effective, 0);
                    return (
                      <tr key={w.id} className="hover:bg-gray-50/50">
                        <td className="px-6 py-3 font-medium text-gray-900">{w.name}</td>
                        <td className="px-6 py-3 text-gray-500 text-xs">{w.owner ?? "—"}</td>
                        {quarterMonths.map((month) => {
                          const mData = w.months.find((m) => m.month === month);
                          return (
                            <td key={month} className="px-4 py-3 text-right font-mono text-gray-700">
                              {mData ? (
                                <span className={mData.invoiced !== null ? "text-blue-700" : "text-gray-400"}>
                                  {fmt(mData.effective)}
                                </span>
                              ) : <span className="text-gray-300">—</span>}
                            </td>
                          );
                        })}
                        <td className="px-6 py-3 text-right font-mono font-semibold text-gray-900">{fmt(qTotal)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </main>

      {/* Email modal */}
      {emailModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
            <div className="px-6 py-5 border-b border-gray-100 flex items-center justify-between">
              <h3 className="text-base font-semibold text-gray-900">Notify Workload Owners</h3>
              <button onClick={() => setEmailModal(false)} className="text-gray-400 hover:text-gray-600">
                <CloseIcon className="w-5 h-5" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <p className="text-sm text-gray-600">
                Send a consumption summary email to all workload owners for the selected quarter.
              </p>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-gray-700">Quarter</label>
                <select
                  value={emailQuarter}
                  onChange={(e) => setEmailQuarter(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {QUARTERS.map((q, i) => (
                    <option key={i} value={i}>{q.label} — {fyLabel}</option>
                  ))}
                </select>
              </div>

              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-700 space-y-1">
                <p className="font-medium">Email will include:</p>
                <ul className="list-disc list-inside space-y-0.5 text-blue-600">
                  <li>Monthly breakdown for each workload the owner manages</li>
                  <li>Invoiced vs forecast amounts per month</li>
                  <li>Quarter total with networking cost allocation</li>
                </ul>
              </div>

              {emailResult && (
                <div className={`rounded-lg px-4 py-3 text-sm ${
                  emailResult.ok ? "bg-green-50 border border-green-200 text-green-800" : "bg-red-50 border border-red-200 text-red-800"
                }`}>
                  {emailResult.message}
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
              <button onClick={() => setEmailModal(false)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 rounded-lg">
                Cancel
              </button>
              <button
                onClick={sendEmails}
                disabled={sending}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {sending ? <><SpinIcon className="w-4 h-4 animate-spin" />Sending…</> : <><MailIcon className="w-4 h-4" />Send Emails</>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MailIcon({ className }: { className?: string }) {
  return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>;
}
function CloseIcon({ className }: { className?: string }) {
  return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>;
}
function SpinIcon({ className }: { className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>;
}
