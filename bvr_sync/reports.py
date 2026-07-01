"""LAPORAN & ALERT — query views di Supabase → kirim ringkasan ke WhatsApp.

Dua bundel (sesuai permintaan):
  run_stock()  → stok tinggal N hari, restock mendesak, dead stock
  run_trend()  → borongan, tren naik/turun 12 jam (Shopee & TikTok), top seller

Butuh view dari supabase_reports.sql sudah dibuat di Supabase.
"""
from __future__ import annotations
from . import config
from .supabase_client import SupabaseClient
from .notifier import send_whatsapp
from .logger import get_logger

log = get_logger()


# ── util ─────────────────────────────────────────────────────────────────────
def _rp(n) -> str:
    try:
        return "Rp" + f"{float(n):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "Rp0"


def _num(n) -> str:
    try:
        f = float(n)
        return str(int(f)) if f == int(f) else f"{f:.1f}"
    except (TypeError, ValueError):
        return "0"


def _send(title: str, lines: list[str]) -> None:
    """Kirim satu blok pesan (dipotong biar tak kepanjangan)."""
    if not lines:
        return
    shown = lines[:20]
    more = f"\n… +{len(lines) - 20} lainnya" if len(lines) > 20 else ""
    send_whatsapp(f"{title}\n" + "\n".join(shown) + more)


# ── ALERT STOK ───────────────────────────────────────────────────────────────
def report_low_stock(sb: SupabaseClient) -> int:
    rows = sb.select("v_sales_velocity", "item_code,item_name,total_available,avg_daily_14d,days_of_cover", {
        "days_of_cover": f"lte.{config.STOCK_ALERT_DAYS}",
        "avg_daily_14d": "gt.0",
        "order": "days_of_cover.asc",
        "limit": "50",
    })
    lines = [
        f"• {r['item_code']} — sisa {_num(r['total_available'])} pcs "
        f"(~{_num(r['days_of_cover'])} hari, jual {_num(r['avg_daily_14d'])}/hari)"
        for r in rows
    ]
    _send(f"⚠️ STOK MENIPIS (≤{config.STOCK_ALERT_DAYS} hari) — {len(rows)} SKU", lines)
    return len(rows)


def report_restock_urgent(sb: SupabaseClient) -> int:
    rows = sb.select("v_restock_urgent", "item_code,item_name,avg_daily_14d,qty_7d,po_pending", {
        "order": "qty_7d.desc", "limit": "50",
    })
    lines = [
        f"• {r['item_code']} — STOK HABIS, laku {_num(r['qty_7d'])}/7hr"
        + (f", PO jalan {_num(r['po_pending'])}" if float(r.get('po_pending') or 0) > 0 else ", PO belum ada")
        for r in rows
    ]
    _send(f"🚨 RESTOCK MENDESAK (stok 0 tapi laku) — {len(rows)} SKU", lines)
    return len(rows)


def report_dead_stock(sb: SupabaseClient) -> int:
    rows = sb.select("v_dead_stock", "item_code,item_name,total_on_hand,modal_nyangkut", {
        "modal_nyangkut": "gt.0",
        "order": "modal_nyangkut.desc",
        "limit": "30",
    })
    total_modal = sum(float(r.get("modal_nyangkut") or 0) for r in rows)
    lines = [
        f"• {r['item_code']} — {_num(r['total_on_hand'])} pcs, modal {_rp(r['modal_nyangkut'])}"
        for r in rows
    ]
    _send(f"🧊 DEAD STOCK (>30 hari tak laku) — {len(rows)} SKU, total {_rp(total_modal)}", lines)
    return len(rows)


def run_stock() -> dict:
    sb = SupabaseClient()
    try:
        log.info("[report][stock] Mulai alert stok.")
        a = report_low_stock(sb)
        b = report_restock_urgent(sb)
        c = report_dead_stock(sb)
        log.info(f"[report][stock] Selesai — menipis={a}, restock={b}, dead={c}")
        return {"ok": True, "low_stock": a, "restock": b, "dead": c}
    except Exception as e:
        log.exception(f"[report][stock] GAGAL: {e}")
        send_whatsapp(f"🚨 Laporan STOK gagal: {str(e)[:300]}")
        return {"ok": False, "error": str(e)}
    finally:
        sb.close()


# ── ALERT TREN & BORONGAN ────────────────────────────────────────────────────
def report_bulk_orders(sb: SupabaseClient) -> int:
    rows = sb.select("v_bulk_orders",
                     "salesorder_no,channel,customer_name,item_code,item_name,qty,amount,transaction_date", {
        "qty": f"gte.{config.BULK_MIN_QTY}",
        "order": "qty.desc",
        "limit": "30",
    })
    lines = [
        f"• {_num(r['qty'])}x {r['item_code']} — {r['channel']} "
        f"({r['salesorder_no']}, {_rp(r['amount'])})"
        for r in rows
    ]
    _send(f"📦 BORONGAN (≥{config.BULK_MIN_QTY} pcs/order, {config.BULK_WINDOW_HRS}h) — {len(rows)} order", lines)
    return len(rows)


def report_sales_spike(sb: SupabaseClient) -> int:
    rows = sb.select("v_sales_trend_12h", "item_code,item_name,channel,qty_now,qty_prev", {"limit": "1000"})
    channels = set(config.TREND_CHANNELS)
    naik, turun = [], []
    for r in rows:
        if r.get("channel", "").upper() not in channels:
            continue
        now = float(r.get("qty_now") or 0)
        prev = float(r.get("qty_prev") or 0)
        if now >= config.SPIKE_MIN_QTY and now >= prev * config.SPIKE_RATIO and now > prev:
            delta = f"+{int(now - prev)}" if prev else f"+{int(now)} (baru)"
            naik.append((now - prev, f"• 📈 {r['item_code']} [{r['channel']}] "
                                     f"{_num(prev)}→{_num(now)} pcs ({delta})"))
        elif prev >= config.SPIKE_MIN_QTY and now <= prev * 0.5:
            turun.append((prev - now, f"• 📉 {r['item_code']} [{r['channel']}] "
                                      f"{_num(prev)}→{_num(now)} pcs"))
    naik.sort(reverse=True); turun.sort(reverse=True)
    ch = "/".join(config.TREND_CHANNELS)
    _send(f"📈 PENJUALAN NAIK 12 JAM [{ch}] — {len(naik)} SKU", [x[1] for x in naik])
    _send(f"📉 PENJUALAN TURUN 12 JAM [{ch}] — {len(turun)} SKU", [x[1] for x in turun])
    return len(naik) + len(turun)


def report_top_seller(sb: SupabaseClient) -> int:
    rows = sb.select("v_top_seller_24h", "item_code,item_name,channel,qty,omzet", {
        "order": "qty.desc", "limit": str(config.TOP_SELLER_LIMIT),
    })
    lines = [
        f"{i+1}. {r['item_code']} [{r['channel']}] — {_num(r['qty'])} pcs, {_rp(r['omzet'])}"
        for i, r in enumerate(rows)
    ]
    _send(f"🏆 TOP SELLER 24 JAM (Top {config.TOP_SELLER_LIMIT})", lines)
    return len(rows)


def run_trend() -> dict:
    sb = SupabaseClient()
    try:
        log.info("[report][trend] Mulai alert tren & borongan.")
        a = report_bulk_orders(sb)
        b = report_sales_spike(sb)
        c = report_top_seller(sb)
        log.info(f"[report][trend] Selesai — borongan={a}, tren={b}, top={c}")
        return {"ok": True, "bulk": a, "spike": b, "top": c}
    except Exception as e:
        log.exception(f"[report][trend] GAGAL: {e}")
        send_whatsapp(f"🚨 Laporan TREN gagal: {str(e)[:300]}")
        return {"ok": False, "error": str(e)}
    finally:
        sb.close()
