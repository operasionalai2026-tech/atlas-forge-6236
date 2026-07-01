import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

// Trigger & pantau sync manual → memicu workflow GitHub Actions (yang menjalankan
// engine Python di cloud). Token GitHub disimpan server-side (GITHUB_SYNC_TOKEN),
// TIDAK pernah ke browser. Hanya user yang sudah login yang boleh memicu.

const REPO = process.env.GITHUB_REPO || "operasionalai2026-tech/bvr-dashboard";
const WORKFLOW = "sync.yml";

async function getUser() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
}

// POST /api/sync  { mode: "--all" }  → memicu sync
export async function POST(request) {
  if (!(await getUser())) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const token = process.env.GITHUB_SYNC_TOKEN;
  if (!token) {
    return NextResponse.json(
      { error: "GITHUB_SYNC_TOKEN belum di-set di server." },
      { status: 500 }
    );
  }
  let mode = "--all";
  try {
    const body = await request.json();
    if (body?.mode) mode = String(body.mode);
  } catch {
    /* pakai default */
  }

  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { mode } }),
    }
  );

  if (res.status === 204) return NextResponse.json({ ok: true, mode });
  const detail = await res.text();
  return NextResponse.json(
    { error: "Gagal memicu workflow", status: res.status, detail },
    { status: 502 }
  );
}

// GET /api/sync → status run terbaru (untuk polling)
export async function GET() {
  if (!(await getUser())) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const token = process.env.GITHUB_SYNC_TOKEN;
  if (!token) return NextResponse.json({ error: "no token" }, { status: 500 });

  const res = await fetch(
    `https://api.github.com/repos/${REPO}/actions/runs?per_page=1`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      cache: "no-store",
    }
  );
  const d = await res.json();
  const run = d.workflow_runs?.[0] || null;
  return NextResponse.json(
    run
      ? {
          status: run.status, // queued | in_progress | completed
          conclusion: run.conclusion, // success | failure | null
          url: run.html_url,
          started: run.run_started_at,
        }
      : {}
  );
}
