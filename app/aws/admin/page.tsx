"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter } from "next/navigation";
import { currentFyYear, FY_MONTH_LABELS } from "@/lib/db/aws-types";
import type { Workload, Profile } from "@/lib/db/aws-types";
import { FySelector } from "@/components/aws/FySelector";

type Tab = "workloads" | "forecast" | "networking" | "invoice" | "cur";

export default function AdminPage() {
  const { user, loading, isAdmin } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("workloads");
  const [fyYear, setFyYear] = useState(currentFyYear());

  useEffect(() => {
    if (!loading && (!user || !isAdmin)) router.push("/aws/dashboard");
  }, [loading, user, isAdmin, router]);

  if (loading) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <h1 className="text-2xl font-bold text-gray-900">Admin Panel</h1>
        <FySelector value={fyYear} onChange={setFyYear} />
      </div>

      {/* Tabs */}
      <div className="border-b flex gap-0">
        {(["workloads", "forecast", "networking", "invoice", "cur"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 -mb-px transition-colors ${
              tab === t
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t === "cur" ? "CUR Upload" : t === "invoice" ? "Invoice Amounts" : t === "networking" ? "Networking" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "workloads" && <WorkloadsTab />}
      {tab === "forecast" && <ForecastTab fyYear={fyYear} />}
      {tab === "networking" && <NetworkingTab fyYear={fyYear} />}
      {tab === "invoice" && <InvoiceTab fyYear={fyYear} />}
      {tab === "cur" && <CurUploadTab />}
    </div>
  );
}

// ── Workloads Tab ─────────────────────────────────────────────

function WorkloadsTab() {
  const [workloads, setWorkloads] = useState<Workload[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [form, setForm] = useState({ name: "", owner_email: "", owner_name: "", category: "", aws_account_id: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const [wl, pr] = await Promise.all([
      fetch("/api/aws/workloads").then((r) => r.json()),
      fetch("/api/aws/workloads").then(() => [] as Profile[]), // profiles not needed here
    ]);
    setWorkloads(wl);
  }

  useEffect(() => { load(); }, []);

  async function save() {
    setSaving(true);
    setError("");
    const res = await fetch("/api/aws/workloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!res.ok) {
      const d = await res.json();
      setError(d.error ?? "Error");
    } else {
      setForm({ name: "", owner_email: "", owner_name: "", category: "", aws_account_id: "" });
      await load();
    }
    setSaving(false);
  }

  async function deactivate(id: number) {
    await fetch("/api/aws/workloads", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await load();
  }

  return (
    <div className="space-y-6">
      {/* Add form */}
      <div className="bg-white rounded-xl shadow p-6">
        <h2 className="font-semibold text-gray-800 mb-4">Add / Update Workload</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Workload Name *" value={form.name} onChange={(v) => setForm((f) => ({ ...f, name: v }))} />
          <Field label="Owner Name" value={form.owner_name} onChange={(v) => setForm((f) => ({ ...f, owner_name: v }))} />
          <Field label="Owner Email" type="email" value={form.owner_email} onChange={(v) => setForm((f) => ({ ...f, owner_email: v }))} />
          <Field label="Category" value={form.category} onChange={(v) => setForm((f) => ({ ...f, category: v }))} />
          <Field label="AWS Account ID" value={form.aws_account_id} onChange={(v) => setForm((f) => ({ ...f, aws_account_id: v }))} />
        </div>
        {error && <p className="text-red-600 text-sm mt-2">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !form.name}
          className="mt-4 bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Workload"}
        </button>
      </div>

      {/* List */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Owner</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Category</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">AWS Account</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {workloads.map((w) => (
              <tr key={w.id} className="hover:bg-gray-50">
                <td className="px-4 py-2.5 font-medium text-gray-900">{w.name}</td>
                <td className="px-4 py-2.5 text-gray-600">{w.owner_name ?? "—"} {w.owner_email ? `<${w.owner_email}>` : ""}</td>
                <td className="px-4 py-2.5 text-gray-500">{w.category ?? "—"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-gray-500">{w.aws_account_id ?? "—"}</td>
                <td className="px-4 py-2.5 text-right">
                  <button onClick={() => deactivate(w.id)} className="text-red-500 text-xs hover:underline">Deactivate</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Forecast Tab ──────────────────────────────────────────────

function ForecastTab({ fyYear }: { fyYear: number }) {
  const [workloads, setWorkloads] = useState<Workload[]>([]);
  const [selectedWl, setSelectedWl] = useState<number | "">("");
  const [forecasts, setForecasts] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch("/api/aws/workloads").then((r) => r.json()).then(setWorkloads);
  }, []);

  useEffect(() => {
    if (!selectedWl) return;
    fetch(`/api/aws/monthly?fy_year=${fyYear}&workload_id=${selectedWl}`)
      .then((r) => r.json())
      .then((data) => {
        const f: Record<number, string> = {};
        for (const row of data) f[row.month_in_fy] = String(row.forecast_amount ?? "");
        setForecasts(f);
      });
  }, [selectedWl, fyYear]);

  async function save() {
    if (!selectedWl) return;
    setSaving(true);
    for (const [monthStr, amtStr] of Object.entries(forecasts)) {
      const month = Number(monthStr);
      const amt = parseFloat(amtStr || "0");
      await fetch("/api/aws/monthly", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workload_id: selectedWl,
          fy_year: fyYear,
          month_in_fy: month,
          forecast_amount: amt,
        }),
      });
    }
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow p-6">
        <h2 className="font-semibold text-gray-800 mb-4">Set Monthly Forecasts — {fyLabel}</h2>
        <p className="text-sm text-gray-500 mb-4">
          Enter monthly forecast amounts per workload. These are used until an invoice is received from Telstra (typically 2 months later).
        </p>

        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">Workload</label>
          <select
            value={selectedWl}
            onChange={(e) => setSelectedWl(Number(e.target.value) || "")}
            className="border rounded px-3 py-1.5 text-sm w-64"
          >
            <option value="">Select a workload…</option>
            {workloads.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>

        {selectedWl && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3 mb-4">
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <div key={m}>
                  <label className="block text-xs font-medium text-gray-600 mb-1">{FY_MONTH_LABELS[m]}</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={forecasts[m] ?? ""}
                    onChange={(e) => setForecasts((f) => ({ ...f, [m]: e.target.value }))}
                    className="border rounded px-2 py-1 text-sm w-full"
                    placeholder="0.00"
                  />
                </div>
              ))}
            </div>

            <button
              onClick={save}
              disabled={saving}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : saved ? "Saved ✓" : "Save Forecasts"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Networking Tab ────────────────────────────────────────────

function NetworkingTab({ fyYear }: { fyYear: number }) {
  const LINES = ["Transit Gateway", "VPN / Direct Connect", "Data Transfer Out", "Other Networking"];
  const [amounts, setAmounts] = useState<Record<string, Record<number, string>>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`/api/aws/networking?fy_year=${fyYear}`)
      .then((r) => r.json())
      .then((data) => {
        const a: Record<string, Record<number, string>> = {};
        for (const row of data) {
          const desc = row.description ?? "Other Networking";
          if (!a[desc]) a[desc] = {};
          a[desc][row.month_in_fy] = String(row.amount ?? "");
        }
        setAmounts(a);
      });
  }, [fyYear]);

  async function save() {
    setSaving(true);
    for (const desc of LINES) {
      for (let m = 1; m <= 12; m++) {
        const amt = parseFloat(amounts[desc]?.[m] || "0");
        if (amt > 0) {
          await fetch("/api/aws/networking", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fy_year: fyYear, month_in_fy: m, description: desc, amount: amt }),
          });
        }
      }
    }
    // Redistribute after saving
    for (let m = 1; m <= 12; m++) {
      await fetch("/api/aws/redistribute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fy_year: fyYear, month_in_fy: m }),
      });
    }
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  return (
    <div className="bg-white rounded-xl shadow p-6 space-y-4">
      <h2 className="font-semibold text-gray-800">Shared Networking Costs — {fyLabel}</h2>
      <p className="text-sm text-gray-500">
        Enter the 4 networking line items (rows A17–A20 in Excel). These will be distributed proportionally across workloads each month.
      </p>

      <div className="overflow-x-auto">
        <table className="text-sm w-full">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-3 py-2 font-medium text-gray-600 w-44">Line Item</th>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <th key={m} className="px-2 py-2 font-medium text-gray-600 text-center min-w-[72px]">{FY_MONTH_LABELS[m]}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {LINES.map((line) => (
              <tr key={line}>
                <td className="px-3 py-2 text-gray-700 text-xs">{line}</td>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <td key={m} className="px-1 py-1">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={amounts[line]?.[m] ?? ""}
                      onChange={(e) =>
                        setAmounts((a) => ({
                          ...a,
                          [line]: { ...(a[line] ?? {}), [m]: e.target.value },
                        }))
                      }
                      className="border rounded px-1 py-0.5 w-full text-right text-xs"
                      placeholder="0"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
      >
        {saving ? "Saving & Redistributing…" : saved ? "Saved ✓" : "Save & Redistribute"}
      </button>
    </div>
  );
}

// ── Invoice Amounts Tab ───────────────────────────────────────

function InvoiceTab({ fyYear }: { fyYear: number }) {
  const [workloads, setWorkloads] = useState<Workload[]>([]);
  const [selectedWl, setSelectedWl] = useState<number | "">("");
  const [invoices, setInvoices] = useState<Record<number, string>>({});
  const [adjustments, setAdjustments] = useState<Record<number, string>>({});
  const [savingW, setSavingW] = useState(false);
  const [savingA, setSavingA] = useState(false);
  const [saved, setSaved] = useState(false);
  const [savedA, setSavedA] = useState(false);

  useEffect(() => {
    fetch("/api/aws/workloads").then((r) => r.json()).then(setWorkloads);
    fetch(`/api/aws/invoice-adjustment?fy_year=${fyYear}`)
      .then((r) => r.json())
      .then((data) => {
        const a: Record<number, string> = {};
        for (const row of data) a[row.month_in_fy] = String(row.amount ?? "");
        setAdjustments(a);
      });
  }, [fyYear]);

  useEffect(() => {
    if (!selectedWl) return;
    fetch(`/api/aws/monthly?fy_year=${fyYear}&workload_id=${selectedWl}`)
      .then((r) => r.json())
      .then((data) => {
        const f: Record<number, string> = {};
        for (const row of data) if (row.invoiced_amount !== null) f[row.month_in_fy] = String(row.invoiced_amount);
        setInvoices(f);
      });
  }, [selectedWl, fyYear]);

  async function saveInvoices() {
    if (!selectedWl) return;
    setSavingW(true);
    for (const [monthStr, amtStr] of Object.entries(invoices)) {
      if (!amtStr) continue;
      await fetch("/api/aws/monthly", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workload_id: selectedWl,
          fy_year: fyYear,
          month_in_fy: Number(monthStr),
          invoiced_amount: parseFloat(amtStr),
        }),
      });
    }
    setSavingW(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function saveAdjustments() {
    setSavingA(true);
    for (const [monthStr, amtStr] of Object.entries(adjustments)) {
      const amt = parseFloat(amtStr || "0");
      await fetch("/api/aws/invoice-adjustment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fy_year: fyYear, month_in_fy: Number(monthStr), amount: amt }),
      });
    }
    // Redistribute
    for (let m = 1; m <= 12; m++) {
      await fetch("/api/aws/redistribute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fy_year: fyYear, month_in_fy: m }),
      });
    }
    setSavingA(false);
    setSavedA(true);
    setTimeout(() => setSavedA(false), 2000);
  }

  const fyLabel = `FY${String(fyYear + 1).slice(-2)}`;

  return (
    <div className="space-y-6">
      {/* Invoice amounts per workload */}
      <div className="bg-white rounded-xl shadow p-6">
        <h2 className="font-semibold text-gray-800 mb-2">Invoiced Amounts per Workload — {fyLabel}</h2>
        <p className="text-sm text-gray-500 mb-4">
          Once the Telstra invoice arrives (typically 2 months later), enter the actual invoiced amounts here.
        </p>
        <div className="mb-4">
          <select
            value={selectedWl}
            onChange={(e) => setSelectedWl(Number(e.target.value) || "")}
            className="border rounded px-3 py-1.5 text-sm w-64"
          >
            <option value="">Select a workload…</option>
            {workloads.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>

        {selectedWl && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3 mb-4">
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <div key={m}>
                  <label className="block text-xs font-medium text-gray-600 mb-1">{FY_MONTH_LABELS[m]}</label>
                  <input
                    type="number" step="0.01" min="0"
                    value={invoices[m] ?? ""}
                    onChange={(e) => setInvoices((f) => ({ ...f, [m]: e.target.value }))}
                    className="border rounded px-2 py-1 text-sm w-full"
                    placeholder="Leave blank if not yet received"
                  />
                </div>
              ))}
            </div>
            <button onClick={saveInvoices} disabled={savingW}
              className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50">
              {savingW ? "Saving…" : saved ? "Saved ✓" : "Save Invoice Amounts"}
            </button>
          </>
        )}
      </div>

      {/* Invoice adjustments (U16/Z16/AE16 pattern) */}
      <div className="bg-white rounded-xl shadow p-6">
        <h2 className="font-semibold text-gray-800 mb-2">Invoice Adjustments — {fyLabel}</h2>
        <p className="text-sm text-gray-500 mb-4">
          Small monthly invoice differences (captured in U16, Z16, AE16… columns in the Excel). Distributed proportionally across workloads.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3 mb-4">
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
            <div key={m}>
              <label className="block text-xs font-medium text-gray-600 mb-1">{FY_MONTH_LABELS[m]}</label>
              <input
                type="number" step="0.01"
                value={adjustments[m] ?? ""}
                onChange={(e) => setAdjustments((f) => ({ ...f, [m]: e.target.value }))}
                className="border rounded px-2 py-1 text-sm w-full"
                placeholder="0.00"
              />
            </div>
          ))}
        </div>
        <button onClick={saveAdjustments} disabled={savingA}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50">
          {savingA ? "Saving…" : savedA ? "Saved ✓" : "Save Adjustments & Redistribute"}
        </button>
      </div>
    </div>
  );
}

// ── CUR Upload Tab ────────────────────────────────────────────

function CurUploadTab() {
  const [uploads, setUploads] = useState<{ id: number; filename: string | null; period_start: string; period_end: string; row_count: number | null; processed: boolean; created_at: string }[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  async function loadUploads() {
    const data = await fetch("/api/aws/cur").then((r) => r.json());
    setUploads(data);
  }

  useEffect(() => { loadUploads(); }, []);

  async function upload() {
    if (!file || !periodStart || !periodEnd) return;
    setUploading(true);
    setError("");
    setResult("");

    const text = await file.text();
    let rows: Record<string, string>[] = [];

    // Parse CSV
    const lines = text.split("\n").filter((l) => l.trim());
    if (lines.length > 1) {
      const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
      rows = lines.slice(1).map((line) => {
        const vals = line.split(",").map((v) => v.trim().replace(/^"|"$/g, ""));
        return Object.fromEntries(headers.map((h, i) => [h, vals[i] ?? ""]));
      });
    }

    // Normalise: expect columns "workload_name" (or "lineItem/ProductCode") and "amount" (or "lineItem/UnblendedCost")
    const normalised = rows.map((r) => ({
      workload_name: r["workload_name"] ?? r["product/ProductName"] ?? r["lineItem/ProductCode"] ?? r["WorkloadName"] ?? "",
      amount: r["amount"] ?? r["lineItem/UnblendedCost"] ?? r["Cost"] ?? "0",
    })).filter((r) => r.workload_name);

    const res = await fetch("/api/aws/cur", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, period_start: periodStart, period_end: periodEnd, rows: normalised }),
    });

    if (!res.ok) {
      const d = await res.json();
      setError(d.error ?? "Upload failed");
    } else {
      const d = await res.json();
      setResult(`Uploaded successfully. ${d.workloads_updated} workloads updated.`);
      await loadUploads();
    }
    setUploading(false);
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl shadow p-6">
        <h2 className="font-semibold text-gray-800 mb-2">Upload AWS CUR File</h2>
        <p className="text-sm text-gray-500 mb-4">
          Upload a bi-weekly CUR CSV file. The file must have columns: <code className="bg-gray-100 px-1 rounded">workload_name</code> and <code className="bg-gray-100 px-1 rounded">amount</code> (or standard AWS CUR column names).
          Workloads not in the exclusion list will be aggregated under "Others".
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">CUR File (CSV)</label>
            <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Period Start</label>
            <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm w-full" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Period End</label>
            <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm w-full" />
          </div>
        </div>

        {error && <p className="text-red-600 text-sm mb-2">{error}</p>}
        {result && <p className="text-green-600 text-sm mb-2">{result}</p>}

        <button
          onClick={upload}
          disabled={uploading || !file || !periodStart || !periodEnd}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload CUR"}
        </button>
      </div>

      {/* Upload history */}
      <div className="bg-white rounded-xl shadow overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h2 className="font-semibold text-gray-700">Upload History</h2>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">File</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Period</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Rows</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Uploaded</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {uploads.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400">No uploads yet</td></tr>
            ) : uploads.map((u) => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-4 py-2.5 text-gray-700">{u.filename ?? "—"}</td>
                <td className="px-4 py-2.5 text-gray-600">{u.period_start} → {u.period_end}</td>
                <td className="px-4 py-2.5 text-right">{u.row_count ?? "—"}</td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${u.processed ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                    {u.processed ? "Processed" : "Pending"}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-gray-500 text-xs">{new Date(u.created_at).toLocaleString("en-AU")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; type?: string
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <input
        type={type} value={value} onChange={(e) => onChange(e.target.value)}
        className="border rounded px-2 py-1.5 text-sm w-full focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
    </div>
  );
}
