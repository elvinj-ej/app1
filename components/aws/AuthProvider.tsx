"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "@/lib/db/client";
import type { User } from "@supabase/supabase-js";
import type { Profile } from "@/lib/db/aws-types";

interface AuthCtx {
  user: User | null;
  profile: Profile | null;
  loading: boolean;
  isAdmin: boolean;
}

const Ctx = createContext<AuthCtx>({ user: null, profile: null, loading: true, isAdmin: false });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadProfile(u: User | null) {
    if (!u) { setProfile(null); setLoading(false); return; }
    const { data } = await supabase
      .from("profiles")
      .select("id, display_name, email, role, created_at")
      .eq("id", u.id)
      .single();
    setProfile(data as Profile | null);
    setLoading(false);
  }

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user: u } }) => {
      setUser(u);
      loadProfile(u);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_e, session) => {
      setUser(session?.user ?? null);
      loadProfile(session?.user ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  return (
    <Ctx.Provider value={{ user, profile, loading, isAdmin: profile?.role === "admin" }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
