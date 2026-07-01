"""MODUL 3 — Preorder/PO Stock.

Tarik data PO yang belum dipenuhi dari `inbound-purchase-not-fulfilled`.
Tabel `preorder_stocks`: 1 baris per PO line item.

qty_pending = qty_po - qty_fulfilled
"""
from __future__ import annotations
import uuid
from . import config, notifier
from .jubelio_client import JubelioClient
from .supabase_client import SupabaseClient
from .logger import get_logger
from .utils import to_float, to_int

log = get_logger()


def _map_preorder(item: dict) -> dict:
    qty_po = to_float(item.get("qty_in_base")) or 0
    qty_fulf = to_float(item.get("qty_fulfilled")) or 0
    return {
        "item_id":           to_int(item.get("item_id")),
        "item_code":         (item.get("item_code") or "").strip() or None,
        "item_name":         item.get("item_name"),
        "purchaseorder_no":  item.get("purchaseorder_no"),
        "qty_po":            qty_po,
        "qty_fulfilled":     qty_fulf,
        "qty_pending":       qty_po - qty_fulf,
        "location_id":       to_int(item.get("location_id")),
        "location_name":     item.get("location_name"),
        "transaction_date":  item.get("transaction_date"),
        "variation_values":  item.get("variation_values"),
        "thumbnail":         item.get("thumbnail"),
        "source_channel":    "jubelio",
    }


def run(jub: JubelioClient | None = None,
        sb: SupabaseClient | None = None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    own_jub, own_sb = jub is None, sb is None
    jub = jub or JubelioClient()
    sb = sb or SupabaseClient()
    processed, failed = 0, 0
    log.info(f"[preorder][{run_id}] Mulai sync PO/Inbound stock.")

    try:
        page, total = 1, None
        while True:
            data = jub.list_preorder(page, config.PAGE_SIZE)
            items = data.get("data", [])
            if total is None:
                total = data.get("totalCount", 0)
            if not items:
                break

            # dedup per (PO, item, lokasi) supaya upsert composite tidak error
            dedup: dict[tuple, dict] = {}
            for it in items:
                if not (it.get("item_code") or "").strip():
                    continue
                r = _map_preorder(it)
                dedup[(r["purchaseorder_no"], r["item_id"], r["location_id"])] = r
            rows = list(dedup.values())
            # 1 PO punya banyak item → kunci = PO + item + lokasi
            sb.upsert("preorder_stocks", rows,
                      on_conflict="purchaseorder_no,item_id,location_id")
            processed += len(rows)

            log.info(f"[preorder][{run_id}] halaman {page} — {processed}/{total} PO")
            if processed >= (total or 0):
                break
            page += 1

        log.info(f"[preorder][{run_id}] Selesai — {processed} PO.")
        sb.log_run(run_id, "preorder", "success", processed, failed, None,
                   {"total": total})
        notifier.notify_success("preorder", processed)
        return {"ok": True, "processed": processed}

    except Exception as e:
        error_msg = str(e)
        failed += 1
        log.exception(f"[preorder][{run_id}] GAGAL: {error_msg}")
        sb.log_run(run_id, "preorder", "failed", processed, failed, error_msg, None)
        notifier.notify_failure("preorder", error_msg)
        return {"ok": False, "processed": processed, "error": error_msg}
    finally:
        if own_jub:
            jub.close()
        if own_sb:
            sb.close()
