import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import Analytics from "@/app/components/Analytics";

export const dynamic = "force-dynamic";

export default async function AnalyticsPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  return <Analytics email={user.email} />;
}
