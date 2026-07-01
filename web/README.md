# BVR-DB Dashboard (Next.js) — Deploy ke Vercel

Dashboard web dengan **login aman (Supabase Auth)** + **RLS**. Hanya menampilkan
data (read-only) — sync data dilakukan oleh engine Python via GitHub Actions.

## Arsitektur

```
┌─────────────────┐      ┌──────────────┐      ┌─────────────────────┐
│ GitHub Actions  │─────▶│   Supabase   │◀─────│  Dashboard (Vercel) │
│ (cron sync)     │write │  (Postgres)  │ read │  Next.js + login     │
│ pakai service_  │      │  + RLS       │ anon │  pakai anon key      │
│ role key        │      └──────────────┘      └─────────────────────┘
└─────────────────┘
   engine Python                                    user login (tim)
```

- **Tulis data** hanya oleh GitHub Actions (service_role, bypass RLS).
- **Baca data** oleh dashboard, hanya untuk user yang **sudah login** (RLS).

---

## A. Siapkan database (sekali)

Di Supabase → SQL Editor, jalankan **berurutan**:
1. `supabase_schema.sql`  — tabel
2. `supabase_reports.sql` — view laporan
3. `supabase_rls.sql`     — keamanan (RLS) ← wajib untuk login

## B. Buat akun tim

Supabase → **Authentication → Users → Add user** (isi email + password) untuk tiap
anggota tim. Lalu **Authentication → Providers → Email → matikan "Enable sign ups"**
supaya hanya user undangan yang bisa masuk (tidak ada pendaftaran publik).

## C. Deploy dashboard ke Vercel

1. Push repo ini ke GitHub (pastikan `env` TIDAK ikut — sudah di `.gitignore`).
2. Buka [vercel.com](https://vercel.com) → **Add New → Project** → import repo.
3. **Root Directory**: set ke `web`.
4. **Environment Variables** (Settings → Environment Variables):
   - `NEXT_PUBLIC_SUPABASE_URL` = `https://prskutrtlegzlvaebxvq.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = anon key (Supabase → Settings → API)
   > Hanya **anon key** — JANGAN pernah taruh service_role di sini.
5. **Deploy**. Selesai → buka URL Vercel → muncul halaman login.

### Netlify (alternatif)
Sama saja: base directory `web`, build `npm run build`, publish otomatis (plugin
Next.js), isi env var yang sama.

## D. Jalankan lokal (dev)

```bash
cd web
cp .env.example .env.local   # isi anon key
npm install
npm run dev                  # http://localhost:3000
```

---

## Catatan keamanan
- `.env.local` & `env` sudah di-`.gitignore` — jangan pernah commit.
- service_role key **hanya** ada di GitHub Actions Secrets (untuk sync), tidak di
  dashboard/browser.
- RLS memastikan data tak bisa dibaca tanpa login.
