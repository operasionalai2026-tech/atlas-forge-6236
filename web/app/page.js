import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import Dashboard from "./components/Dashboard";

export const dynamic = "force-dynamic";

export default async function Home() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  return <Dashboard email={user.email} />;
}
