"""Entry point CLI — Integrasi Jubelio → Supabase.

Contoh:
  python run_sync.py --all                 # produk + order (incremental)
  python run_sync.py --products            # hanya master produk
  python run_sync.py --orders              # hanya penjualan (incremental)
  python run_sync.py --orders --lookback-days 30   # backfill 30 hari terakhir
  python run_sync.py --check               # cek konfigurasi & koneksi saja

Dipakai oleh scheduler (Task Scheduler / cron) — lihat README.
"""
from __future__ import annotations
import argparse
import sys
from bvr_sync import config
from bvr_sync.logger import get_logger

log = get_logger()


def _preflight(require_supabase: bool = True) -> bool:
    missing = config.validate(require_supabase=require_supabase)
    if missing:
        log.error("Konfigurasi belum lengkap. Isi di file `env`: " + ", ".join(missing))
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync Jubelio → Supabase")
    ap.add_argument("--all", action="store_true", help="Jalankan produk + order")
    ap.add_argument("--products", action="store_true", help="Sync master produk (katalog + HPP + stok)")
    ap.add_argument("--stock-only", action="store_true",
                    help="Refresh cepat HPP + stok saja (inventory/v2, tanpa detail katalog)")
    ap.add_argument("--orders", action="store_true", help="Sync penjualan (incremental)")
    ap.add_argument("--preorder", action="store_true", help="Sync PO/Inbound stock (belum dipenuhi)")
    ap.add_argument("--report-stock", action="store_true",
                    help="Kirim alert STOK ke WhatsApp (menipis/restock/dead stock)")
    ap.add_argument("--report-trend", action="store_true",
                    help="Kirim alert TREN ke WhatsApp (borongan/naik-turun 12j/top seller)")
    ap.add_argument("--lookback-days", type=int, default=None,
                    help="Paksa scan N hari ke belakang (backfill). Default: pakai watermark.")
    ap.add_argument("--check", action="store_true", help="Cek konfigurasi & koneksi, lalu keluar")
    args = ap.parse_args()

    if args.check:
        ok = _preflight()
        if ok:
            from bvr_sync.jubelio_client import JubelioClient
            from bvr_sync.supabase_client import SupabaseClient
            try:
                with JubelioClient() as j:
                    j.login()
                with SupabaseClient() as s:
                    s.select("sync_state", "module", {"limit": "1"})
                log.info("✅ Konfigurasi OK — Jubelio & Supabase terhubung.")
            except Exception as e:
                log.error(f"❌ Gagal cek koneksi: {e}")
                return 1
        return 0 if ok else 1

    if not (args.all or args.products or args.stock_only or args.orders
            or args.preorder or args.report_stock or args.report_trend):
        ap.print_help()
        return 1

    if not _preflight():
        return 1

    rc = 0
    # produk dulu supaya master siap sebelum cek SKU-match di modul order
    if args.all or args.products or args.stock_only:
        from bvr_sync import sync_products
        res = sync_products.run(stock_only=args.stock_only and not (args.all or args.products))
        rc = rc or (0 if res.get("ok") else 2)

    if args.all or args.orders:
        from bvr_sync import sync_orders
        res = sync_orders.run(lookback_days=args.lookback_days)
        rc = rc or (0 if res.get("ok") else 2)

    if args.all or args.preorder:
        from bvr_sync import sync_preorder
        res = sync_preorder.run()
        rc = rc or (0 if res.get("ok") else 2)

    # laporan/alert (jalan setelah sync supaya data terbaru)
    if args.report_stock:
        from bvr_sync import reports
        reports.run_stock()

    if args.report_trend:
        from bvr_sync import reports
        reports.run_trend()

    return rc


if __name__ == "__main__":
    sys.exit(main())
