"""MODUL RETUR — retur penjualan online (credit note) dari /sales/sales-returns/.

Murah: endpoint list sudah memuat semua kolom yang kita butuhkan (tidak perlu
detail per dokumen), jadi 1 call Jubelio = 100 retur, ditulis batch ke Supabase.

Incremental sama seperti orders: sort last_modified DESC, berhenti di cutoff
(watermark - overlap). Upsert by doc_id.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from . import config, notifier
from .jubelio_client import JubelioClient
from .supabase_client import SupabaseClient
from .logger import get_logger
from .utils import to_float, to_int, to_ts

log = get_logger()


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _map_return(d: dict) -> dict:
    return {
        "doc_id":           to_int(d.get("doc_id")),
        "doc_number":       d.get("doc_number"),
        "doc_type":         d.get("doc_type"),
        "salesorder_id":    to_int(d.get("salesorder_id")),
        "ref_no":           d.get("ref_no"),
        "ref_no_return":    d.get("ref_no_return"),
        "return_type":      d.get("return_type"),
        "customer_name":    d.get("customer_name"),
        "so_customer_name": d.get("so_customer_name"),
        "store_id":         to_int(d.get("store_id")),
        "store_name":       d.get("store_name"),
        "source":           d.get("source"),
        "grand_total":      to_float(d.get("grand_total")),
        "transaction_date": to_ts(d.get("transaction_date")),
        "created_date":     to_ts(d.get("created_date")),
        "last_modified":    to_ts(d.get("last_modified")),
    }


def run(lookback_days: int | None = None,
        jub: JubelioClient | None = None,
        sb: SupabaseClient | None = None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    own_jub, own_sb = jub is None, sb is None
    jub = jub or JubelioClient()
    sb = sb or SupabaseClient()
    processed, failed = 0, 0
    max_modified: datetime | None = None

    watermark = sb.get_watermark("returns")
    wm_dt = _parse_dt(watermark)
    if lookback_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    elif wm_dt:
        cutoff = wm_dt - timedelta(minutes=config.WATERMARK_OVERLAP_MIN)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.SYNC_LOOKBACK_DAYS)

    log.info(f"[returns][{run_id}] Mulai sync retur. cutoff >= {cutoff.isoformat()}")

    try:
        page = 1
        stop = False
        while not stop:
            data = jub.list_returns(page, config.PAGE_SIZE)
            rows = data.get("data", [])
            if not rows:
                break

            batch: list[dict] = []
            for row in rows:
                lm = _parse_dt(row.get("last_modified")) or _parse_dt(row.get("created_date"))
                if lm and lm < cutoff:
                    stop = True
                    break
                r = _map_return(row)
                if r["doc_id"] is None:
                    continue
                batch.append(r)
                if lm and (max_modified is None or lm > max_modified):
                    max_modified = lm

            if batch:
                sb.upsert("sales_returns", batch, on_conflict="doc_id")
                processed += len(batch)
            page += 1

        if max_modified and (wm_dt is None or max_modified > wm_dt):
            sb.set_watermark("returns", max_modified.isoformat())

        log.info(f"[returns][{run_id}] Selesai — {processed} retur tersinkron.")
        sb.log_run(run_id, "returns", "success", processed, failed, None,
                   {"new_watermark": max_modified.isoformat() if max_modified else None})
        return {"ok": True, "processed": processed, "failed": failed}

    except Exception as e:
        error_msg = str(e)
        log.exception(f"[returns][{run_id}] GAGAL: {error_msg}")
        sb.log_run(run_id, "returns", "failed", processed, failed, error_msg, None)
        notifier.notify_failure("returns", error_msg)
        return {"ok": False, "processed": processed, "error": error_msg}
    finally:
        if own_jub:
            jub.close()
        if own_sb:
            sb.close()
