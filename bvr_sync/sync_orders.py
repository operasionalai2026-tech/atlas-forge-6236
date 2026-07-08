"""MODUL 1 — Penjualan (header order + item per SKU).

Strategi incremental (dioptimasi untuk volume besar + anti rate-limit):
  1. LIGHT PASS  — dari endpoint list (100 order/call) langsung bulk-upsert
     header ringkas (status, total, channel). Murah: 1 call Jubelio + 1 call
     Supabase per halaman. Data omzet/status selalu segar walau detail belum.
  2. SKIP UNCHANGED — order yang last_modified-nya sama dengan yang sudah ada
     di DB dilewati (tidak fetch detail). Menghemat panggilan detail untuk
     window overlap yang di-scan ulang tiap run.
  3. DETAIL BATCH — detail (items + finansial) diambil per order, tapi ditulis
     ke Supabase secara batch per DETAIL_FLUSH order (bukan 3 call per order).

  - Order di-sort `last_modified DESC`; berhenti paging saat < cutoff.
  - cutoff = watermark_terakhir - overlap, atau (now - lookback_days).
  - Catatan: light pass TIDAK menulis last_modified — kolom itu hanya ditulis
    oleh detail pass, sehingga order yang gagal detail akan dicoba lagi.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from . import config, notifier
from .jubelio_client import JubelioClient
from .supabase_client import SupabaseClient
from .logger import get_logger
from .utils import to_float, to_int, to_bool, to_ts

log = get_logger()


# ── parsing tanggal ──────────────────────────────────────────────────────────
def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _first(*vals):
    for v in vals:
        if v not in (None, ""):
            return v
    return None


# ── mapping header ───────────────────────────────────────────────────────────
def _map_order(d: dict) -> dict:
    return {
        "salesorder_id":        to_int(d.get("salesorder_id")),
        "salesorder_no":        d.get("salesorder_no"),
        "ref_no":               d.get("ref_no"),
        "invoice_no":           d.get("invoice_no"),
        "invoice_id":           to_int(d.get("invoice_id")),
        "store_so_number":      d.get("store_so_number"),
        "source":               to_int(d.get("source")),
        "source_name":          d.get("source_name"),
        "store_id":             to_int(d.get("store_id")),
        "store_name":           d.get("store_name"),
        "transaction_date":     to_ts(d.get("transaction_date")),
        "created_date":         to_ts(d.get("created_date")),
        "payment_date":         to_ts(_first(d.get("payment_date"),
                                             d.get("mp_timestamp") if d.get("is_paid") else None)),
        "awb_created_date":     to_ts(_first(d.get("awb_created_date"), d.get("tn_created_date"))),
        "shipped_date":         to_ts(_first(d.get("shipped_date"), d.get("tn_created_date"))),
        "completed_date":       to_ts(_first(d.get("completed_date"), d.get("mp_completed_date"),
                                             d.get("marked_as_complete"))),
        "mp_completed_date":    to_ts(d.get("mp_completed_date")),
        "due_date":             to_ts(d.get("due_date")),
        "last_modified":        to_ts(d.get("last_modified")),
        "status":               d.get("internal_status") or d.get("wms_status"),
        "channel_status":       d.get("channel_status"),
        "wms_status":           d.get("wms_status"),
        "is_paid":              to_bool(d.get("is_paid")),
        "is_cod":               to_bool(d.get("is_cod")),
        "is_canceled":          to_bool(d.get("is_canceled")),
        "cancel_reason":        _first(d.get("cancel_reason"), d.get("mp_cancel_reason")),
        "customer_name":        d.get("customer_name"),
        "shipping_full_name":   d.get("shipping_full_name"),
        "shipping_address":     d.get("shipping_address"),
        "shipping_area":        d.get("shipping_area"),
        "shipping_city":        d.get("shipping_city"),
        "shipping_province":    d.get("shipping_province"),
        "shipping_post_code":   d.get("shipping_post_code"),
        "shipping_phone":       _first(d.get("shipping_phone"), d.get("customer_phone")),
        "courier":              _first(d.get("courier"), d.get("shipper")),
        "shipper":              d.get("shipper"),
        "tracking_number":      _first(d.get("tracking_number"), d.get("tracking_no")),
        "sub_total":            to_float(d.get("sub_total")),
        "total_disc":           to_float(d.get("total_disc")),
        "total_tax":            to_float(d.get("total_tax")),
        "add_disc":             to_float(d.get("add_disc")),
        "add_fee":              to_float(d.get("add_fee")),
        "service_fee":          to_float(d.get("service_fee")),
        "shipping_cost":        to_float(d.get("shipping_cost")),
        "buyer_shipping_cost":  to_float(d.get("buyer_shipping_cost")),
        "insurance_cost":       to_float(d.get("insurance_cost")),
        "voucher_amount":       to_float(d.get("voucher_amount")),
        "discount_marketplace": to_float(d.get("discount_marketplace")),
        "cod_fee":              to_float(d.get("cod_fee")),
        "order_processing_fee": to_float(d.get("order_processing_fee")),
        "grand_total":          to_float(d.get("grand_total")),
        "total_amount_mp":      to_float(d.get("total_amount_mp")),
        "escrow_amount":        to_float(d.get("escrow_amount")),   # NET SETTLEMENT
        "sum_cogs":             to_float(d.get("sum_cogs")),
        "total_weight_kg":      to_float(d.get("total_weight_in_kg")),
        "note":                 d.get("note"),
        "source_channel":       "jubelio",
    }


def _map_order_light(d: dict) -> dict:
    """Header ringkas dari baris LIST (tanpa detail). Kolom yang tak ada di list
    tidak disertakan → PostgREST tidak menimpanya saat update.
    PENTING: last_modified sengaja TIDAK ditulis di sini (lihat docstring modul)."""
    return {
        "salesorder_id":      to_int(d.get("salesorder_id")),
        "salesorder_no":      d.get("salesorder_no"),
        "ref_no":             d.get("ref_no"),
        "invoice_no":         d.get("invoice_no"),
        "store_id":           to_int(d.get("store_id")),
        "store_name":         d.get("store_name"),
        "source_name":        d.get("source_name") or d.get("channel_name"),
        "transaction_date":   to_ts(d.get("transaction_date")),
        "created_date":       to_ts(d.get("created_date")),
        "status":             d.get("internal_status") or d.get("wms_status"),
        "channel_status":     d.get("channel_status"),
        "wms_status":         d.get("wms_status"),
        "is_paid":            to_bool(d.get("is_paid")),
        "is_cod":             to_bool(d.get("is_cod")),
        "is_canceled":        to_bool(d.get("is_canceled")),
        "cancel_reason":      d.get("cancel_reason"),
        "customer_name":      d.get("customer_name"),
        "shipping_full_name": d.get("shipping_full_name"),
        "courier":            d.get("shipper"),
        "shipper":            d.get("shipper"),
        "tracking_number":    d.get("tracking_number"),
        "grand_total":        to_float(d.get("grand_total")),
        "note":               d.get("note"),
        "source_channel":     "jubelio",
    }


def _existing_last_modified(sb: SupabaseClient, ids: list[int]) -> dict[int, datetime]:
    """last_modified yang sudah tersimpan di DB untuk kumpulan order id."""
    out: dict[int, datetime] = {}
    for i in range(0, len(ids), 100):
        chunk = ",".join(str(x) for x in ids[i:i + 100])
        rows = sb.select("orders", "salesorder_id,last_modified",
                         {"salesorder_id": f"in.({chunk})"})
        for r in rows:
            dt = _parse_dt(r.get("last_modified"))
            if dt:
                out[r["salesorder_id"]] = dt
    return out


def _map_item(d: dict, order_id: int, order_no: str) -> dict:
    return {
        "salesorder_detail_id":   to_int(d.get("salesorder_detail_id")),
        "order_id":               order_id,
        "salesorder_no":          order_no,
        "item_id":                to_int(d.get("item_id")),
        "item_code":              (d.get("item_code") or "").strip() or None,
        "item_name":              d.get("item_name"),
        "variant":                d.get("variant"),
        "qty":                    to_float(d.get("qty")),
        "unit":                   d.get("unit"),
        "price":                  to_float(d.get("price")),
        "sell_price":             to_float(d.get("sell_price")),
        "original_price":         to_float(d.get("original_price")),
        "disc_percent":           to_float(d.get("disc")),
        "disc_amount":            to_float(d.get("disc_amount")),
        "disc_marketplace":       to_float(d.get("disc_marketplace")),
        "tax_amount":             to_float(d.get("tax_amount")),
        "amount":                 to_float(d.get("amount")),
        "weight_gram":            to_float(d.get("weight_in_gram")),
        "loc_id":                 to_int(d.get("loc_id")),
        "loc_name":               d.get("loc_name"),
        "item_group_id":          to_int(d.get("item_group_id")),
        "channel_order_detail_id": (str(d["channel_order_detail_id"])
                                    if d.get("channel_order_detail_id") is not None else None),
        "promotion_id":           to_int(d.get("promotion_id")),
        "promotion_name":         d.get("promotion_name"),
        "is_canceled_item":       to_bool(d.get("is_canceled_item")),
        "is_return_resolved":     to_bool(d.get("is_return_resolved")),
        "status":                 d.get("status"),
    }


# ── cek SKU tak match ────────────────────────────────────────────────────────
def _check_unmatched(sb: SupabaseClient, codes: set[str]) -> list[str]:
    codes = {c for c in codes if c}
    if not codes:
        return []
    found: set[str] = set()
    codes_list = list(codes)
    for i in range(0, len(codes_list), 100):
        chunk = codes_list[i:i + 100]
        quoted = ",".join('"' + c.replace('"', '') + '"' for c in chunk)
        rows = sb.select("products", "item_code", {"item_code": f"in.({quoted})"})
        found.update(r["item_code"] for r in rows)
    return sorted(codes - found)


# ── main ─────────────────────────────────────────────────────────────────────
def run(lookback_days: int | None = None,
        jub: JubelioClient | None = None,
        sb: SupabaseClient | None = None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    own_jub, own_sb = jub is None, sb is None
    jub = jub or JubelioClient()
    sb = sb or SupabaseClient()
    processed, failed = 0, 0
    seen_codes: set[str] = set()
    max_modified: datetime | None = None

    # tentukan cutoff
    watermark = sb.get_watermark("orders")
    wm_dt = _parse_dt(watermark)
    if lookback_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    elif wm_dt:
        cutoff = wm_dt - timedelta(minutes=config.WATERMARK_OVERLAP_MIN)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.SYNC_LOOKBACK_DAYS)

    log.info(f"[orders][{run_id}] Mulai sync. cutoff last_modified >= {cutoff.isoformat()}")

    try:
        # ── FASE 1: scan list + light bulk upsert ─────────────────────────────
        candidates: list[tuple[int, datetime | None]] = []   # (so_id, last_modified)
        page = 1
        stop = False
        while not stop:
            data = jub.list_orders(page, config.PAGE_SIZE)
            rows = data.get("data", [])
            if not rows:
                break

            light_batch: list[dict] = []
            for row in rows:
                lm = _parse_dt(row.get("last_modified"))
                if lm and lm < cutoff:
                    stop = True
                    break
                so_id = to_int(row.get("salesorder_id"))
                if so_id is None:
                    continue
                light_batch.append(_map_order_light(row))
                candidates.append((so_id, lm))

            if light_batch:
                sb.upsert("orders", light_batch, on_conflict="salesorder_id")
            if page % 10 == 0:
                log.info(f"[orders][{run_id}] Light pass… hal {page}, {len(candidates)} order terkumpul")
            page += 1

        # dedupe kandidat by salesorder_id (pagination bisa balikan id kembar)
        uniq: dict[int, datetime | None] = {}
        for sid, lm in candidates:
            if sid not in uniq or (lm and (uniq[sid] is None or lm > uniq[sid])):
                uniq[sid] = lm
        candidates = list(uniq.items())
        log.info(f"[orders][{run_id}] Light pass selesai: {len(candidates)} order unik dalam window.")

        # ── FASE 2: lewati yang last_modified-nya tak berubah ─────────────────
        existing = _existing_last_modified(sb, [sid for sid, _ in candidates])
        todo: list[tuple[int, datetime | None]] = []
        skipped = 0
        for sid, lm in candidates:
            db_lm = existing.get(sid)
            if lm and db_lm and abs((lm - db_lm).total_seconds()) < 1:
                skipped += 1                     # sudah sinkron penuh — lewati
                if max_modified is None or lm > max_modified:
                    max_modified = lm
            else:
                todo.append((sid, lm))
        if skipped:
            log.info(f"[orders][{run_id}] {skipped} order tak berubah — dilewati.")

        # ── FASE 3: detail per order, tulis batch per DETAIL_FLUSH ────────────
        buf_headers: list[dict] = []
        buf_items: list[dict] = []
        buf_ids: list[int] = []

        flush_failed = [0]  # pakai list agar bisa dimutasi dari closure

        def _flush():
            nonlocal buf_headers, buf_items, buf_ids
            if not buf_headers:
                return
            try:
                sb.upsert("orders", buf_headers, on_conflict="salesorder_id")
                sb.delete_in("order_items", "order_id", buf_ids)
                if buf_items:
                    sb.upsert("order_items", buf_items, on_conflict="salesorder_detail_id")
            except Exception as e:
                flush_failed[0] += len(buf_headers)
                log.warning(f"[orders][{run_id}] flush {len(buf_headers)} order gagal: {e}")
            finally:
                # SELALU reset buffer — supaya batch buruk tidak diulang terus
                buf_headers, buf_items, buf_ids = [], [], []

        for sid, lm in todo:
            try:
                detail = jub.get_order_detail(sid)
                header = _map_order(detail)
                items = [_map_item(it, sid, header["salesorder_no"])
                         for it in (detail.get("items") or [])]
            except Exception as e:
                failed += 1
                log.warning(f"[orders][{run_id}] detail order {sid} gagal: {e}")
                continue

            buf_headers.append(header)
            buf_ids.append(sid)
            buf_items.extend(items)
            seen_codes.update(i["item_code"] for i in items if i["item_code"])
            processed += 1
            if lm and (max_modified is None or lm > max_modified):
                max_modified = lm
            if len(buf_headers) >= config.DETAIL_FLUSH:
                _flush()
            if processed % 100 == 0:
                log.info(f"[orders][{run_id}] {processed}/{len(todo)} order tersinkron…")
        _flush()
        failed += flush_failed[0]

        # update watermark hanya kalau maju
        if max_modified and (wm_dt is None or max_modified > wm_dt):
            sb.set_watermark("orders", max_modified.isoformat())

        # cek SKU tak match → notifikasi
        unmatched = _check_unmatched(sb, seen_codes)
        if unmatched:
            log.warning(f"[orders][{run_id}] {len(unmatched)} SKU tak match master: {unmatched[:20]}")
            notifier.notify_unmatched(unmatched)

        status = "partial" if failed else "success"
        log.info(f"[orders][{run_id}] Selesai — {processed} detail, {skipped} dilewati "
                 f"(tak berubah), {failed} gagal, {len(unmatched)} SKU tak match.")
        sb.log_run(run_id, "orders", status, processed, failed, None,
                   {"unmatched_skus": unmatched[:100],
                    "skipped_unchanged": skipped,
                    "new_watermark": max_modified.isoformat() if max_modified else None})
        notifier.notify_success("orders", processed,
                                extra=(f"\n⚠️ {len(unmatched)} SKU tak match." if unmatched else ""))
        return {"ok": True, "processed": processed, "failed": failed, "unmatched": unmatched}

    except Exception as e:
        error_msg = str(e)
        log.exception(f"[orders][{run_id}] GAGAL: {error_msg}")
        sb.log_run(run_id, "orders", "failed", processed, failed, error_msg, None)
        notifier.notify_failure("orders", error_msg)
        return {"ok": False, "processed": processed, "error": error_msg}
    finally:
        if own_jub:
            jub.close()
        if own_sb:
            sb.close()
