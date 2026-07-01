# BVR-DB — Integrasi Otomatis Jubelio → Supabase

Sistem sinkronisasi terjadwal dari **Jubelio** ke **Supabase**, terdiri dari dua modul:

| Modul | Fungsi | Tabel Supabase |
|-------|--------|----------------|
| **Penjualan** (`sync_orders`) | Tarik semua transaksi order (semua status: baru, packing, dikirim, selesai, cancel, retur) — header + item per SKU, termasuk net settlement (`escrow_amount`) untuk hitung margin riil. | `orders`, `order_items` |
| **Master Produk** (`sync_products`) | Gabungan **halaman Product Master** (`items/masters` + `catalog/{id}` → nama master, kategori, brand, **berat**, variasi, daftar SKU) dan **`inventory/v2`** (HPP `last_cogs`, stok real-time, breakdown per gudang), digabung per `item_id`. | `products`, `product_stocks` |

Plus: **logging** (file + tabel `sync_log`), **watermark incremental** (`sync_state`), dan **notifikasi WhatsApp via Fonnte** saat gagal / ada SKU tak match.

---

## 1. Prasyarat

- **Python 3.10+** terpasang. Cek: `python --version`.
  > Di mesin ini Python belum ada di PATH — install dari [python.org](https://www.python.org/downloads/) dan centang *"Add Python to PATH"*, atau set `PYTHON_EXE` (lihat penjadwalan).
- **Node.js 18+** terpasang (dipakai untuk notifikasi WhatsApp/Fonnte via `notify.js`). Cek: `node --version`.
  > Kalau `node` tidak di PATH, set `NODE_EXE` ke path `node.exe`.
- Akun **Supabase** (project sudah dibuat).
- (Opsional) Akun **Fonnte** untuk notifikasi WhatsApp.

## 2. Instalasi

```powershell
cd C:\Users\user\Documents\BVR-DB
pip install -r requirements.txt
```

Notifikasi (Node.js) **tidak butuh `npm install`** — `notify.js` zero-dependency
(pakai `fetch` bawaan Node 18+). Uji cepat setelah kredensial Fonnte diisi:

```powershell
node notify.js "Tes notifikasi BVR-DB"
```

## 3. Buat tabel di Supabase

Buka **Supabase Dashboard → SQL Editor**, tempel isi [`supabase_schema.sql`](supabase_schema.sql), lalu **Run**. Aman dijalankan ulang (idempotent).

## 4. Isi kredensial

Edit file **`env`** (sudah ada di folder). Yang wajib:

```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...        # Settings → API → service_role (secret)
```

Opsional (notifikasi):

```
FONNTE_TOKEN=xxxxxxxx
FONNTE_TARGET=6281234567890
```

Kredensial Jubelio (`EMAIL_JUBELIO`, `PASSWORD_JUBELIO`) sudah terisi.

## 5. Uji koneksi

```powershell
python run_sync.py --check
```

Kalau muncul `✅ Konfigurasi OK` berarti siap.

## 6. Menjalankan

```powershell
python run_sync.py --products                 # master lengkap: katalog + HPP + stok
python run_sync.py --stock-only               # refresh cepat HPP + stok saja (tanpa detail katalog)
python run_sync.py --orders                   # penjualan incremental
python run_sync.py --all                       # keduanya (produk dulu, lalu order)

# Backfill riwayat (mis. 30 hari terakhir) untuk run pertama:
python run_sync.py --orders --lookback-days 30
```

> **Run pertama order:** karena Jubelio punya ~jutaan order historis dan tidak
> ada filter tanggal server-side, jangan backfill semua. Mulai dari
> `--lookback-days 30` (atau sesuai kebutuhan). Setelah itu sistem pakai
> **watermark** (`last_modified` terakhir) sehingga run berikutnya hanya menarik
> order yang **baru atau berubah status** — ringan & cepat.

---

## 7. Menjadwalkan (Windows Task Scheduler)

Gunakan wrapper [`run_sync.ps1`](run_sync.ps1). Contoh perintah `schtasks`
(jalankan di PowerShell **as Administrator**, sesuaikan `-WorkingDirectory`):

**A. Stok + HPP — tiap 2 jam** (cepat, `inventory/v2` saja):

```powershell
schtasks /Create /TN "BVR Jubelio Stock" /SC HOURLY /MO 2 ^
  /TR "powershell -ExecutionPolicy Bypass -File \"C:\Users\user\Documents\BVR-DB\run_sync.ps1\" -Args \"--stock-only\"" ^
  /RL LIMITED /F
```

**A2. Master produk lengkap — 1x/hari** (katalog: nama/kategori/berat/varian). Lebih
lama karena menarik detail `catalog/{id}` per master (~2.362 master):

```powershell
schtasks /Create /TN "BVR Jubelio Products" /SC DAILY /ST 03:00 ^
  /TR "powershell -ExecutionPolicy Bypass -File \"C:\Users\user\Documents\BVR-DB\run_sync.ps1\" -Args \"--products\"" ^
  /RL LIMITED /F
```

**B. Penjualan — tiap 15 menit** (order incremental):

```powershell
schtasks /Create /TN "BVR Jubelio Orders" /SC MINUTE /MO 15 ^
  /TR "powershell -ExecutionPolicy Bypass -File \"C:\Users\user\Documents\BVR-DB\run_sync.ps1\" -Args \"--orders\"" ^
  /RL LIMITED /F
```

Kalau `python` tidak di PATH, set path-nya sekali untuk akun:

```powershell
setx PYTHON_EXE "C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe"
```

Cek/hapus task:

```powershell
schtasks /Query /TN "BVR Jubelio Orders"
schtasks /Delete /TN "BVR Jubelio Orders" /F
```

### Alternatif Linux/server (cron)

```cron
# produk tiap 3 jam, order tiap 15 menit
0 */3 * * *  cd /path/BVR-DB && /usr/bin/python3 run_sync.py --products >> logs/cron.log 2>&1
*/15 * * * * cd /path/BVR-DB && /usr/bin/python3 run_sync.py --orders   >> logs/cron.log 2>&1
```

---

## 8. Hasil & analisa

- **`orders`** — 1 baris per order (header). `escrow_amount` = **net settlement**
  (yang benar-benar diterima). Semua status tercatat via kolom `status`,
  `channel_status`, `wms_status`, `is_canceled`.
- **`order_items`** — 1 baris per SKU per order: qty, harga, diskon per item,
  diskon marketplace, subtotal bersih (`amount`), berat.
- **`v_order_item_margin`** (view) — margin riil per baris:
  `revenue_line - (last_cogs × qty)` dengan join HPP master. Contoh:

  ```sql
  select item_code, sum(qty) qty, sum(revenue_line) omzet,
         sum(cogs_line) hpp, sum(gross_margin_line) margin
  from v_order_item_margin
  group by item_code order by margin desc;
  ```

- **`v_unmatched_skus`** (view) — SKU di penjualan yang tak ada di master produk.
- **`products` / `product_stocks`** — HPP, stok total, dan stok per gudang.

## 9. Logging & notifikasi

- File log harian: `logs/sync_YYYY-MM-DD.log`.
- Tabel `sync_log`: riwayat tiap run (status, jumlah record, error).
- Fonnte WhatsApp: dikirim lewat **`notify.js` (Node.js)** saat **gagal** dan saat
  ada **SKU tak match** (juga ringkasan sukses). Python menyusun pesan lalu
  memanggil `node notify.js` (pesan via STDIN). Kosongkan
  `FONNTE_TOKEN`/`FONNTE_TARGET` untuk menonaktifkan.

## 10. Catatan / batasan

- **Berat produk** (`products.weight_gram`) diambil dari `package_weight` di detail
  katalog master (mode `--products`). Mode `--stock-only` tidak mengisi berat/kategori
  (hanya HPP + stok). Berat per baris penjualan juga terekam di `order_items.weight_gram`.
- **Kategori** disimpan sebagai `item_category_id` + `item_group_name` (nama master);
  nama kategori (string) perlu lookup terpisah bila dibutuhkan.
- **HPP & stok tidak ada di endpoint master/katalog** — keduanya diambil dari
  `inventory/v2` lalu digabung per `item_id`. Karena itu `--products` menarik dua
  sumber sekaligus.
- API Jubelio membatasi rate (429). Client sudah menangani retry + backoff +
  jeda antar request (`REQUEST_DELAY_MS`). Naikkan bila masih sering kena limit.
- **`escrow_list`** (rincian potongan settlement) kadang `null` di API; nilai
  bersih tetap ada di `escrow_amount`.

## Struktur kode

```
run_sync.py             # entry point CLI
run_sync.ps1            # wrapper Task Scheduler
supabase_schema.sql     # DDL tabel + view
notify.js               # pengirim Fonnte/WhatsApp (Node.js, zero-dependency)
package.json            # metadata Node (engine >=18)
bvr_sync/
  config.py             # muat env + konstanta
  logger.py             # logging file + console
  jubelio_client.py     # login + GET (retry/backoff/429)
  supabase_client.py    # upsert/delete/select via PostgREST
  notifier.py           # menyusun pesan -> panggil notify.js (Node)
  sync_products.py      # MODUL 2 master produk
  sync_orders.py        # MODUL 1 penjualan
  utils.py              # parsing aman
```
