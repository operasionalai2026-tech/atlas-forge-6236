import { createBrowserClient } from "@supabase/ssr";

// Client Supabase untuk komponen browser (pakai anon key + sesi login).
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}
