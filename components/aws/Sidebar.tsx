"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/components/aws/AuthProvider";
import { supabase } from "@/lib/db/client";

const ADMIN_NAV = [
  {
    section: "Operations",
    items: [
      { href: "/aws/dashboard", label: "Overview", icon: GridIcon },
      { href: "/aws/cur-upload", label: "CUR Upload", icon: UploadIcon },
      { href: "/aws/invoice", label: "Invoices & Comms", icon: MailIcon },
    ],
  },
  {
    section: "Workloads",
    items: [
      { href: "/aws/workloads", label: "All Workloads", icon: LayersIcon },
      { href: "/aws/admin", label: "Admin Settings", icon: SettingsIcon },
    ],
  },
];

const OWNER_NAV = [
  {
    section: "My Workloads",
    items: [
      { href: "/aws/my-workloads", label: "My Dashboard", icon: GridIcon },
      { href: "/aws/workloads", label: "Browse Workloads", icon: LayersIcon },
    ],
  },
];

export function Sidebar() {
  const { profile, isAdmin } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const nav = isAdmin ? ADMIN_NAV : OWNER_NAV;

  async function signOut() {
    await supabase.auth.signOut();
    router.push("/aws/login");
  }

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  if (pathname === "/aws/login") return null;

  return (
    <aside
      className={`flex flex-col bg-slate-900 text-slate-300 transition-all duration-200 ${
        collapsed ? "w-16" : "w-60"
      } min-h-screen shrink-0`}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 py-5 border-b border-slate-800">
        <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center shrink-0">
          <CloudIcon className="w-4 h-4 text-white" />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <p className="text-sm font-semibold text-white truncate">AWS Tracker</p>
            <p className="text-xs text-slate-500 truncate">Cochlear Cloud Platform</p>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="ml-auto text-slate-500 hover:text-slate-300 shrink-0"
        >
          <ChevronIcon collapsed={collapsed} />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 overflow-y-auto">
        {nav.map((section) => (
          <div key={section.section} className="mb-4">
            {!collapsed && (
              <p className="px-4 mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                {section.section}
              </p>
            )}
            {section.items.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg text-sm transition-colors ${
                    active
                      ? "bg-blue-600 text-white"
                      : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                  }`}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {active && !collapsed && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-blue-300" />}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* User */}
      <div className="border-t border-slate-800 p-3">
        <div className={`flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-slate-800 group ${collapsed ? "justify-center" : ""}`}>
          <div className="w-7 h-7 rounded-full bg-blue-500 flex items-center justify-center shrink-0">
            <span className="text-xs font-bold text-white">
              {(profile?.email ?? "?")[0].toUpperCase()}
            </span>
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-slate-300 truncate">{profile?.email}</p>
              <p className="text-[10px] text-slate-500">{isAdmin ? "Admin" : "Workload Owner"}</p>
            </div>
          )}
          {!collapsed && (
            <button
              onClick={signOut}
              className="text-slate-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
              title="Sign out"
            >
              <LogoutIcon className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        {collapsed && (
          <button onClick={signOut} className="w-full flex justify-center mt-1 text-slate-500 hover:text-red-400" title="Sign out">
            <LogoutIcon className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </aside>
  );
}

// ── Icons ─────────────────────────────────────────────────────

function GridIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}
function UploadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
    </svg>
  );
}
function MailIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
    </svg>
  );
}
function LayersIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  );
}
function SettingsIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}
function CloudIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
    </svg>
  );
}
function LogoutIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
    </svg>
  );
}
function ChevronIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d={collapsed ? "M9 5l7 7-7 7" : "M15 19l-7-7 7-7"} />
    </svg>
  );
}
