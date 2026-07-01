# BVR-DB — Panduan Deploy (Framework)

Sistem terbagi 2 bagian yang berjalan terpisah:

| Bagian | Teknologi | Jalan di | Fungsi |
|--------|-----------|----------|--------|
| **Engine Sync** | Python (`bvr_sync/`) | **GitHub Actions** (cron) | Tarik Jubelio → tulis Supabase |
| **Dashboard** | Next.js (`web/`) | **Vercel** | Login tim + lihat data |
| **Database** | Supabase (Postgres) | Supabase Cloud | Simpan data + Auth + RLS |

---

## 1. Database (Supabase SQL Editor) — jalankan berurutan
1. [`supabase_schema.sql`](supabase_schema.sql) — tabel
2. [`supabase_reports.sql`](supabase_reports.sql) — view laporan (alert)
3. [`supabase_rls.sql`](supabase_rls.sql) — keamanan RLS (wajib untuk login)

## 2. Akun tim (Supabase → Authentication)
- **Users → Add user** untuk tiap anggota (email + password).
- **Providers → Email → matikan "Enable sign ups"** (cegah daftar publik).

## 3. Push ke GitHub
```bash
cd C:\Users\user\Documents\BVR-DB
git init
git add .
git commit -m "BVR-DB: sync engine + dashboard"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```
> `env` & secret **tidak ikut** (sudah di `.gitignore`). Cek: `git status` — pastikan
> file `env` tidak muncul di daftar yang akan di-commit.

## 4. GitHub Actions — isi Secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Nilai |
|--------|-------|
| `EMAIL_JUBELIO` | email Jubelio |
| `PASSWORD_JUBELIO` | password Jubelio |
| `SUPABASE_URL` | `https://prskutrtlegzlvaebxvq.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | service_role key (rahasia) |
| `FONNTE_TOKEN` | (opsional) token Fonnte |
| `FONNTE_TARGET` | (opsional) nomor WhatsApp |

Workflow [`.github/workflows/sync.yml`](.github/workflows/sync.yml) otomatis jalan:
- tiap 30 mnt → `--orders --report-trend`
- tiap 2 jam → `--stock-only`
- 03:00 WIB → `--products --preorder --report-stock`

Uji manual: tab **Actions → BVR Sync → Run workflow**.

## 5. Dashboard ke Vercel
1. [vercel.com](https://vercel.com) → Add New Project → import repo.
2. **Root Directory: `web`**.
3. Env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (anon saja).
4. Deploy → buka URL → login pakai akun tim.

Detail dashboard: [web/README.md](web/README.md).

---

## Ringkas alur data
```
GitHub Actions (Python, service_role) ──tulis──▶ Supabase ◀──baca (login, RLS)── Vercel (Next.js)
```
- Sync berat aman di GitHub Actions (batas 2 jam/job).
- Dashboard ringan & aman di Vercel (cuma baca, wajib login).
- Alert stok/tren → WhatsApp via Fonnte (dari engine sync).
