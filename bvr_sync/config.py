"""Konfigurasi terpusat — memuat variabel dari file `env` / `.env`.

File kredensial yang sudah ada di folder ini bernama `env` (tanpa titik),
jadi kita muat itu lebih dulu, lalu `.env` bila ada (override).
"""
from __future__ import annotations
import os
from dotenv import load_dotenv

# Muat `env` (nama file existing) lalu `.env` (opsional, menimpa)
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_HERE, "env"))
load_dotenv(os.path.join(_HERE, ".env"), override=True)


def _get(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


def _int(key: str, default: int) -> int:
    try:
        return int(_get(key) or default)
    except (TypeError, ValueError):
        return default


# ── Jubelio ─────────────────────────────────────────────────────────────────
JUBELIO_EMAIL     = _get("EMAIL_JUBELIO")
JUBELIO_PASSWORD  = _get("PASSWORD_JUBELIO")
JUBELIO_LOGIN_URL = _get("JUBELIO_LOGIN_URL", "https://api2.jubelio.com/login")
JUBELIO_BASE_URL  = _get("JUBELIO_BASE_URL",  "https://open.jubelio.com/core-api")
ORDERS_PATH       = "/sales/orders/"
ORDER_DETAIL_PATH = "/sales/orders/"          # + {salesorder_id}
INVENTORY_PATH    = "/inventory/v2/"          # sumber HPP + stok + multi-gudang
MASTERS_PATH      = "/inventory/v2/items/masters/"   # daftar produk master (halaman Product Master)
CATALOG_PATH      = "/inventory/v2/catalog/"         # + {item_group_id} : detail master (berat/kategori/varian)
BUNDLE_FILTER     = _int("BUNDLE_FILTER", 1)

# ── Supabase (PostgREST) ────────────────────────────────────────────────────
SUPABASE_URL = _get("SUPABASE_URL")           # https://xxxx.supabase.co
SUPABASE_KEY = _get("SUPABASE_SERVICE_ROLE_KEY") or _get("SUPABASE_KEY")  # service_role disarankan

# ── Fonnte (WhatsApp — jalur fallback via API pihak ketiga) ────────────────
FONNTE_TOKEN  = _get("FONNTE_TOKEN")
FONNTE_TARGET = _get("FONNTE_TARGET")         # nomor tujuan, cth 6281xxxx (boleh koma utk banyak)
FONNTE_URL    = _get("FONNTE_URL", "https://api.fonnte.com/send")

# ── WhatsApp lokal (Baileys, daemon di whatsapp/bot.js — HANYA jalan di PC) ─
# Dicoba LEBIH DULU sebelum Fonnte. Kosongkan WA_GROUP_ID untuk skip jalur ini
# (mis. saat sync jalan di GitHub Actions, di mana daemon lokal tidak terjangkau).
WA_LOCAL_URL = _get("WA_LOCAL_URL", "http://127.0.0.1:4001")
WA_GROUP_ID  = _get("WA_GROUP_ID")            # cth: 120363xxxxxxxxxx@g.us (lihat /groups)

# ── Perilaku sync ───────────────────────────────────────────────────────────
# Berapa hari ke belakang (berdasarkan last_modified) yang di-scan saat incremental.
# Run pertama (backfill) pakai --lookback-days besar via CLI.
SYNC_LOOKBACK_DAYS = _int("SYNC_LOOKBACK_DAYS", 3)
# Overlap keamanan (menit) dari watermark supaya order yg update tepat di batas tidak terlewat.
WATERMARK_OVERLAP_MIN = _int("WATERMARK_OVERLAP_MIN", 30)

# ── Ambang batas laporan/alert ───────────────────────────────────────────────
STOCK_ALERT_DAYS = _int("STOCK_ALERT_DAYS", 5)     # alert kalau stok tinggal <= N hari
BULK_MIN_QTY     = _int("BULK_MIN_QTY", 10)        # borongan: qty >= N dalam 1 baris order
BULK_WINDOW_HRS  = _int("BULK_WINDOW_HRS", 24)     # jendela borongan (jam)
SPIKE_MIN_QTY    = _int("SPIKE_MIN_QTY", 5)        # min qty 12 jam supaya dihitung tren
SPIKE_RATIO      = float(_get("SPIKE_RATIO", "1.5") or 1.5)  # naik kalau now >= prev * ratio
TOP_SELLER_LIMIT = _int("TOP_SELLER_LIMIT", 10)
# channel yang dipantau untuk alert tren (sesuai permintaan: Shopee & TikTok)
TREND_CHANNELS   = [c.strip().upper() for c in
                    (_get("TREND_CHANNELS", "SHOPEE,TIKTOK") or "").split(",") if c.strip()]

PAGE_SIZE           = _int("JUBELIO_PAGE_SIZE", 100)
REQUEST_DELAY_MS    = _int("REQUEST_DELAY_MS", 350)   # jeda AWAL antar request (adaptif)
REQUEST_DELAY_MIN_MS = _int("REQUEST_DELAY_MIN_MS", 150)   # batas bawah saat lancar
REQUEST_DELAY_MAX_MS = _int("REQUEST_DELAY_MAX_MS", 3000)  # batas atas saat sering 429
MAX_RETRIES         = _int("MAX_RETRIES", 5)
UPSERT_BATCH        = _int("UPSERT_BATCH", 500)       # baris per batch ke Supabase
DETAIL_FLUSH        = _int("DETAIL_FLUSH", 50)        # order per flush batch ke Supabase

LOG_DIR = os.path.join(_HERE, "logs")


def validate(require_supabase: bool = True) -> list[str]:
    """Kembalikan daftar kunci konfigurasi yang belum diisi (kosong = siap jalan)."""
    missing = []
    if not JUBELIO_EMAIL:    missing.append("EMAIL_JUBELIO")
    if not JUBELIO_PASSWORD: missing.append("PASSWORD_JUBELIO")
    if require_supabase:
        if not SUPABASE_URL: missing.append("SUPABASE_URL")
        if not SUPABASE_KEY: missing.append("SUPABASE_SERVICE_ROLE_KEY")
    return missing
