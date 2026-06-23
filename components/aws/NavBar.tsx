"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "./AuthProvider";
import { supabase } from "@/lib/db/client";

export function NavBar() {
  const { profile, isAdmin } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (pathname === "/aws/login") return null;

  function active(path: string) {
    return pathname.startsWith(path) ? "bg-blue-700" : "hover:bg-blue-700";
  }

  async function signOut() {
    await supabase.auth.signOut();
    router.push("/aws/login");
  }

  return (
    <nav className="bg-blue-900 text-white px-4 py-3 flex items-center gap-4">
      <span className="font-bold text-lg mr-4">AWS Tracker</span>
      <Link href="/aws/dashboard" className={`px-3 py-1 rounded text-sm ${active("/aws/dashboard")}`}>
        Dashboard
      </Link>
      <Link href="/aws/workloads" className={`px-3 py-1 rounded text-sm ${active("/aws/workloads")}`}>
        Workloads
      </Link>
      {isAdmin && (
        <Link href="/aws/admin" className={`px-3 py-1 rounded text-sm ${active("/aws/admin")}`}>
          Admin
        </Link>
      )}
      <div className="ml-auto flex items-center gap-3 text-sm">
        <span className="text-blue-300">{profile?.email ?? ""}</span>
        {isAdmin && <span className="bg-yellow-500 text-black text-xs px-2 py-0.5 rounded">Admin</span>}
        <button onClick={signOut} className="hover:text-blue-300">Sign out</button>
      </div>
    </nav>
  );
}
