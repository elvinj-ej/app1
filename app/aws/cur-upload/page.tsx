"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/aws/TopBar";

interface UploadRecord {
  id: number;
  uploaded_at: string;
  filename: string;
  status: string;
  rows_processed: number | null;
  error_message: string | null;
}

export default function CurUploadPage() {
  const { user, loading, isAdmin } = useAuth();
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [history, setHistory] = useState<UploadRecord[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

  useEffect(() => {
    if (!loading && !user) router.push("/aws/login");
    if (!loading && !isAdmin) router.push("/aws/dashboard");
  }, [loading, user, isAdmin, router]);

  useEffect(() => {
    if (!user || !isAdmin) return;
    fetch("/api/aws/cur")
      .then((r) => r.json())
      .then((d) => { setHistory(Array.isArray(d) ? d : []); setLoadingHistory(false); });
  }, [user, isAdmin]);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setResult(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/aws/cur", { method: "POST", body: form });
      const data = await res.json();
      if (res.ok) {
        setResult({ ok: true, message: data.message ?? "Upload successful." });
        setFile(null);
        // Refresh history
        fetch("/api/aws/cur").then((r) => r.json()).then((d) => setHistory(Array.isArray(d) ? d : []));
      } else {
        setResult({ ok: false, message: data.error ?? "Upload failed." });
      }
    } catch {
      setResult({ ok: false, message: "Network error. Please try again." });
    }
    setUploading(false);
  }

  if (loading || !isAdmin) return null;

  const fmt = (s: string) => new Date(s).toLocaleDateString("en-AU", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"
  });

  return (
    <div className="flex flex-col min-h-screen">
      <TopBar />
      <main className="flex-1 p-8 space-y-8 max-w-4xl">

        {/* Upload card */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Upload AWS CUR File</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Upload a bi-weekly AWS Cost &amp; Usage Report CSV. Accepted format: AWSCUR with workloads_tag column.
            </p>
          </div>

          <div className="p-6 space-y-4">
            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
              className={`relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed cursor-pointer transition-colors py-12 ${
                dragging
                  ? "border-blue-400 bg-blue-50"
                  : file
                  ? "border-green-400 bg-green-50"
                  : "border-gray-300 bg-gray-50 hover:border-blue-300 hover:bg-blue-50/40"
              }`}
            >
              <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              {file ? (
                <>
                  <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
                    <CheckIcon className="w-5 h-5 text-green-600" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-gray-900">{file.name}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{(file.size / 1024).toFixed(0)} KB — click to change</p>
                  </div>
                </>
              ) : (
                <>
                  <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center">
                    <UploadIcon className="w-5 h-5 text-gray-400" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-gray-700">Drop CSV here or click to browse</p>
                    <p className="text-xs text-gray-400 mt-0.5">AWSCUR format, .csv only</p>
                  </div>
                </>
              )}
            </div>

            {/* Result banner */}
            {result && (
              <div className={`flex items-start gap-3 rounded-lg px-4 py-3 text-sm ${
                result.ok ? "bg-green-50 border border-green-200 text-green-800" : "bg-red-50 border border-red-200 text-red-800"
              }`}>
                {result.ok ? <CheckIcon className="w-4 h-4 mt-0.5 shrink-0 text-green-600" /> : <AlertIcon className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />}
                {result.message}
              </div>
            )}

            <div className="flex items-center gap-3">
              <button
                onClick={handleUpload}
                disabled={!file || uploading}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-2.5 rounded-lg transition-colors"
              >
                {uploading ? (
                  <>
                    <SpinIcon className="w-4 h-4 animate-spin" />
                    Processing…
                  </>
                ) : (
                  <>
                    <UploadIcon className="w-4 h-4" />
                    Import CUR Data
                  </>
                )}
              </button>
              {file && !uploading && (
                <button onClick={() => { setFile(null); setResult(null); }} className="text-sm text-gray-500 hover:text-gray-700">
                  Clear
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Upload history */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-6 py-5 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-900">Upload History</h2>
          </div>
          {loadingHistory ? (
            <div className="px-6 py-8 text-center text-gray-400 text-sm">Loading…</div>
          ) : history.length === 0 ? (
            <div className="px-6 py-8 text-center text-gray-400 text-sm">No uploads yet. Import your first CUR file above.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="text-left px-6 py-3 font-medium text-gray-600">File</th>
                  <th className="text-left px-6 py-3 font-medium text-gray-600">Uploaded</th>
                  <th className="text-left px-6 py-3 font-medium text-gray-600">Rows</th>
                  <th className="text-left px-6 py-3 font-medium text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {history.map((h) => (
                  <tr key={h.id} className="hover:bg-gray-50/50">
                    <td className="px-6 py-3 text-gray-900 font-medium truncate max-w-xs">{h.filename ?? "—"}</td>
                    <td className="px-6 py-3 text-gray-500">{fmt(h.uploaded_at)}</td>
                    <td className="px-6 py-3 text-gray-600">{h.rows_processed ?? "—"}</td>
                    <td className="px-6 py-3">
                      <StatusBadge status={h.status} error={h.error_message} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Format guide */}
        <div className="bg-slate-50 rounded-xl border border-slate-200 p-6 space-y-2">
          <h3 className="text-sm font-semibold text-slate-700">Expected CSV Format</h3>
          <ul className="text-xs text-slate-500 space-y-1">
            <li><span className="font-mono bg-slate-200 px-1 rounded">workloads_tag</span> column maps rows to tracked workloads</li>
            <li>Date columns are numeric Excel serial numbers (e.g. 45870 = Oct 2025)</li>
            <li>Rows with category <span className="font-mono bg-slate-200 px-1 rounded">forecast</span>, <span className="font-mono bg-slate-200 px-1 rounded">sum_monthly_expense</span>, or <span className="font-mono bg-slate-200 px-1 rounded">sum_marketplace</span> are skipped</li>
            <li>Unmatched workloads are bucketed as &quot;Others&quot;</li>
            <li>Networking costs are auto-distributed proportionally after each import</li>
          </ul>
        </div>

      </main>
    </div>
  );
}

function StatusBadge({ status, error }: { status: string; error?: string | null }) {
  if (status === "success") {
    return <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full"><CheckIcon className="w-3 h-3" />Success</span>;
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full" title={error ?? undefined}>
        <AlertIcon className="w-3 h-3" />Failed
      </span>
    );
  }
  return <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full"><SpinIcon className="w-3 h-3 animate-spin" />Processing</span>;
}

function CheckIcon({ className }: { className?: string }) {
  return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>;
}
function UploadIcon({ className }: { className?: string }) {
  return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>;
}
function AlertIcon({ className }: { className?: string }) {
  return <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>;
}
function SpinIcon({ className }: { className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>;
}
