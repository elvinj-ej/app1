"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "./AuthProvider";

const PAGE_TITLES: Record<string, { title: string; subtitle: string }> = {
  "/aws/dashboard":    { title: "Overview",             subtitle: "All workloads consumption summary" },
  "/aws/cur-upload":  { title: "CUR Upload",            subtitle: "Import bi-weekly AWS Cost & Usage Reports" },
  "/aws/invoice":     { title: "Invoices & Comms",      subtitle: "Reconcile Telstra invoices and notify workload owners" },
  "/aws/workloads":   { title: "Workloads",             subtitle: "All tracked AWS workloads" },
  "/aws/admin":       { title: "Admin Settings",        subtitle: "Manage workloads, forecasts, and shared costs" },
  "/aws/my-workloads":{ title: "My Dashboard",          subtitle: "Your workload consumption and forecast" },
};

export function TopBar({ fyLabel, fySelector }: { fyLabel?: string; fySelector?: React.ReactNode }) {
  const pathname = usePathname();
  const { isAdmin } = useAuth();

  const base = Object.keys(PAGE_TITLES).find((k) => pathname === k || pathname.startsWith(k + "/"));
  const meta = base ? PAGE_TITLES[base] : { title: "AWS Tracker", subtitle: "" };

  const today = new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <header className="bg-white border-b border-gray-200 px-8 py-4 flex items-center gap-6">
      <div className="flex-1">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-900">{meta.title}</h1>
          {fyLabel && (
            <span className="bg-blue-50 text-blue-700 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-blue-100">
              {fyLabel}
            </span>
          )}
          {isAdmin && (
            <span className="bg-amber-50 text-amber-700 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-amber-100">
              Admin
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500 mt-0.5">{meta.subtitle}</p>
      </div>
      <div className="flex items-center gap-4">
        {fySelector}
        <p className="text-xs text-gray-400 hidden lg:block">{today}</p>
      </div>
    </header>
  );
}
