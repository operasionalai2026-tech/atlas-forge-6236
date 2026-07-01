"""MODUL 2 — Master Produk.

Sumber data (halaman Product Master Jubelio):
  - items/masters  → daftar master (item_group) + varian
  - catalog/{id}   → detail master: berat, kategori, brand, variasi, daftar SKU
  - inventory/v2   → HPP (last_cogs), stok real-time + breakdown per gudang

Gabungan ketiganya (join per item_id) → tabel `products` (1 baris per SKU)
+ `product_stocks` (per gudang). Full-refresh tiap run (upsert by item_id).

Mode:
  run()                    → lengkap: katalog master + HPP + stok
  run(stock_only=True)     → cepat: hanya HPP + stok dari inventory/v2
"""
from __future__ import annotations
import uuid
from . import config, notifier
from .jubelio_client import JubelioClient
from .supabase_client import SupabaseClient
from .logger import get_logger
from .utils import to_float, to_int, to_bool

log = get_logger()


# ── index inventory: item_id → HPP + stok + lokasi ──────────────────────────
def _build_inventory_index(jub: JubelioClient, run_id: str) -> tuple[dict, list[dict]]:
    index: dict[int, dict] = {}
    stock_rows: list[dict] = []
    page, total = 1, None
    while True:
        data = jub.list_inventory(page, config.PAGE_SIZE)
        items = data.get("data", [])
        if total is None:
            total = data.get("totalCount", 0)
        if not items:
            break
        for it in items:
            iid = to_int(it.get("item_id"))
            if iid is None:
                continue
            tot = it.get("total_stocks") or {}
            index[iid] = {
                "item_code":       (it.get("item_code") or "").strip(),
                "item_name":       it.get("item_name"),
                "brand_name":      it.get("brand_name"),
                "is_bundle":       it.get("is_bundle"),
                "last_cogs":       it.get("last_cogs"),
                "average_cost":    it.get("average_cost"),
                "thumbnail":       it.get("thumbnail"),
                "variation_values": it.get("variation_values"),
                "total_on_hand":   to_float((tot).get("on_hand")) or 0,
                "total_available": to_float((tot).get("available")) or 0,
                "total_reserved":  to_float((tot).get("reserved")) or 0,
                "total_on_order":  to_float((tot).get("on_order")) or 0,
            }
            for loc in (it.get("location_stocks") or []):
                stock_rows.append({
                    "item_id":       iid,
                    "location_id":   to_int(loc.get("location_id")),
                    "location_code": loc.get("location_code"),
                    "on_hand":       to_float(loc.get("on_hand")) or 0,
                    "on_order":      to_float(loc.get("on_order")) or 0,
                    "reserved":      to_float(loc.get("reserved")) or 0,
                    "available":     to_float(loc.get("available")) or 0,
                })
        log.info(f"[products][{run_id}] inventory {len(index)}/{total} SKU")
        if len(index) >= (total or 0):
            break
        page += 1
    return index, stock_rows


# ── mapping 1 SKU (gabungan catalog + inventory) ─────────────────────────────
def _map_row(sku: dict, ctx: dict, inv: dict) -> dict:
    vv = sku.get("variation_values")
    if vv is None:
        vv = inv.get("variation_values")
    return {
        "item_id":          to_int(sku.get("item_id")),
        "item_code":        (sku.get("item_code") or inv.get("item_code") or "").strip(),
        "item_name":        sku.get("item_name") or inv.get("item_name"),
        "item_group_id":    to_int(ctx.get("item_group_id")),
        "item_group_name":  ctx.get("item_group_name"),
        "item_category_id": to_int(ctx.get("item_category_id")),
        "brand_name":       ctx.get("brand_name") or inv.get("brand_name"),
        "barcode":          sku.get("barcode"),
        "variation_name":   sku.get("variation_name"),
        "is_bundle":        to_bool(inv.get("is_bundle")),
        "sell_price":       to_float(sku.get("sell_price")),
        "last_cogs":        to_float(inv.get("last_cogs")),
        "average_cost":     to_float(inv.get("average_cost")),
        "weight_gram":      to_float(ctx.get("package_weight")),
        "package_length":   to_float(ctx.get("package_length")),
        "package_width":    to_float(ctx.get("package_width")),
        "package_height":   to_float(ctx.get("package_height")),
        "total_on_hand":    inv.get("total_on_hand", 0),
        "total_available":  inv.get("total_available", 0),
        "total_reserved":   inv.get("total_reserved", 0),
        "total_on_order":   inv.get("total_on_order", 0),
        "thumbnail":        inv.get("thumbnail"),
        "description":      ctx.get("description"),
        "variation_values": vv,
        "source_channel":   "jubelio",
    }


# baris minimal utk SKU inventory yg tak ada di master (mis. bundle/standalone)
def _map_leftover(iid: int, inv: dict) -> dict:
    return {
        "item_id":          iid,
        "item_code":        inv.get("item_code"),
        "item_name":        inv.get("item_name"),
        "item_group_id":    None,
        "item_group_name":  None,
        "item_category_id": None,
        "brand_name":       inv.get("brand_name"),
        "barcode":          None,
        "variation_name":   None,
        "is_bundle":        to_bool(inv.get("is_bundle")),
        "sell_price":       None,
        "last_cogs":        to_float(inv.get("last_cogs")),
        "average_cost":     to_float(inv.get("average_cost")),
        "weight_gram":      None,
        "package_length":   None, "package_width": None, "package_height": None,
        "total_on_hand":    inv.get("total_on_hand", 0),
        "total_available":  inv.get("total_available", 0),
        "total_reserved":   inv.get("total_reserved", 0),
        "total_on_order":   inv.get("total_on_order", 0),
        "thumbnail":        inv.get("thumbnail"),
        "description":      None,
        "variation_values": inv.get("variation_values"),
        "source_channel":   "jubelio",
    }


def run(stock_only: bool = False,
        jub: JubelioClient | None = None,
        sb: SupabaseClient | None = None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    own_jub, own_sb = jub is None, sb is None
    jub = jub or JubelioClient()
    sb = sb or SupabaseClient()
    processed, failed = 0, 0
    log.info(f"[products][{run_id}] Mulai sync master produk "
             f"({'stok saja' if stock_only else 'katalog + HPP + stok'}).")

    try:
        # 1) HPP + stok dari inventory/v2
        inv_index, stock_rows = _build_inventory_index(jub, run_id)

        # 2) mode cepat: cukup update dari inventory (tanpa detail katalog)
        if stock_only:
            rows = [_map_leftover(iid, inv) for iid, inv in inv_index.items()
                    if (inv.get("item_code") or "").strip()]
            sb.upsert("products", rows, on_conflict="item_id")
            processed = len(rows)
        else:
            # 3) iterasi master → catalog detail → gabung dgn inventory
            seen: set[int] = set()
            page, total = 1, None
            while True:
                data = jub.list_masters(page, config.PAGE_SIZE)
                masters = data.get("data", [])
                if total is None:
                    total = data.get("totalCount", 0)
                if not masters:
                    break
                for m in masters:
                    gid = to_int(m.get("item_group_id"))
                    if gid is None:
                        continue
                    try:
                        cat = jub.get_catalog(gid)
                    except Exception as e:
                        failed += 1
                        log.warning(f"[products][{run_id}] catalog {gid} gagal: {e}")
                        continue
                    ctx = {
                        "item_group_id":    gid,
                        "item_group_name":  cat.get("item_group_name") or m.get("item_name"),
                        "item_category_id": cat.get("item_category_id") or m.get("item_category_id"),
                        "brand_name":       cat.get("brand_name"),
                        "package_weight":   cat.get("package_weight"),
                        "package_length":   cat.get("package_length"),
                        "package_width":    cat.get("package_width"),
                        "package_height":   cat.get("package_height"),
                        "description":      cat.get("description"),
                    }
                    rows = []
                    for sku in (cat.get("product_skus") or []):
                        iid = to_int(sku.get("item_id"))
                        if iid is None or not (sku.get("item_code") or "").strip():
                            continue
                        rows.append(_map_row(sku, ctx, inv_index.get(iid, {})))
                        seen.add(iid)
                    if rows:
                        sb.upsert("products", rows, on_conflict="item_id")
                        processed += len(rows)
                log.info(f"[products][{run_id}] master hal {page} — {processed} SKU (dari {total} master)")
                page += 1

            # 4) SKU inventory yg belum ke-cover master → tambahkan minimal
            leftovers = [_map_leftover(iid, inv) for iid, inv in inv_index.items()
                         if iid not in seen and (inv.get("item_code") or "").strip()]
            if leftovers:
                sb.upsert("products", leftovers, on_conflict="item_id")
                processed += len(leftovers)
                log.info(f"[products][{run_id}] +{len(leftovers)} SKU non-master ditambahkan")

        # 5) stok per gudang
        if stock_rows:
            sb.upsert("product_stocks", stock_rows, on_conflict="item_id,location_id")

        status = "partial" if failed else "success"
        log.info(f"[products][{run_id}] Selesai — {processed} SKU, {failed} master gagal.")
        sb.log_run(run_id, "products", status, processed, failed, None,
                   {"stock_only": stock_only, "stock_rows": len(stock_rows)})
        notifier.notify_success("products", processed,
                                extra=(f"\n⚠️ {failed} master gagal." if failed else ""))
        return {"ok": True, "processed": processed, "failed": failed}

    except Exception as e:
        error_msg = str(e)
        log.exception(f"[products][{run_id}] GAGAL: {error_msg}")
        sb.log_run(run_id, "products", "failed", processed, failed, error_msg, None)
        notifier.notify_failure("products", error_msg)
        return {"ok": False, "processed": processed, "error": error_msg}
    finally:
        if own_jub:
            jub.close()
        if own_sb:
            sb.close()
