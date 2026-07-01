"""BVR-DB — Integrasi otomatis Jubelio → Supabase.

Dua modul utama:
  - sync_orders   : tarik transaksi penjualan (header + item) → tabel orders/order_items
  - sync_products : tarik master produk (HPP, stok, multi-gudang) → tabel products/product_stocks

Jalankan lewat: python run_sync.py --all
"""

__version__ = "1.0.0"
