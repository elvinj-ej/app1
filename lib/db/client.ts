import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

const PLACEHOLDER = "http://localhost";

/** Browser / client-side client — respects RLS, uses anon key. */
export const supabase = createClient(url ?? PLACEHOLDER, anonKey ?? "placeholder");

/**
 * Server-side admin client — bypasses RLS.
 * Only use in API routes / server actions, never in client components.
 */
export function getAdminClient() {
  if (!serviceKey) throw new Error("Missing SUPABASE_SERVICE_ROLE_KEY");
  return createClient(url!, serviceKey, {
    auth: { persistSession: false },
  });
}
