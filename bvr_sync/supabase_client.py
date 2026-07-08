"""Client Supabase via PostgREST (pakai httpx — tanpa dependency tambahan).

Menyediakan upsert (insert-or-update), delete (eq & in), dan select sederhana,
semuanya dengan retry otomatis untuk error transient (5xx / jaringan).
Gunakan SERVICE_ROLE key agar bypass RLS.
"""
from __future__ import annotations
import time
import httpx
from . import config
from .utils import utcnow_iso
from .logger import get_logger

log = get_logger()

_TRANSIENT = (429, 500, 502, 503, 504)


class SupabaseError(Exception):
    pass


class SupabaseClient:
    def __init__(self):
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise SupabaseError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY belum diisi di env.")
        self._base = config.SUPABASE_URL.rstrip("/") + "/rest/v1"
        self._client = httpx.Client(timeout=60, headers={
            "apikey": config.SUPABASE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_KEY}",
            "Content-Type": "application/json",
        })

    # ── request dengan retry transient ─────────────────────────────────────────
    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        last = None
        for attempt in range(1, 4):
            try:
                resp = self._client.request(method, url, **kw)
                if resp.status_code in _TRANSIENT:
                    last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    time.sleep(1.5 ** attempt)
                    continue
                return resp
            except httpx.RequestError as e:
                last = str(e)
                time.sleep(1.5 ** attempt)
        raise SupabaseError(f"{method} {url} gagal setelah retry: {last}")

    # ── upsert (batch, on_conflict) ────────────────────────────────────────────
    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> int:
        if not rows:
            return 0
        # DEDUPE by kunci konflik — Postgres tidak boleh punya 2 baris dengan
        # nilai konflik sama dalam 1 command (error 21000). Ambil yang terakhir
        # (data paling baru). Wajib karena sumber bisa kirim id kembar (mis.
        # pagination Jubelio yg di-sort last_modified).
        keys = [k.strip() for k in on_conflict.split(",")]
        deduped: dict[tuple, dict] = {}
        for r in rows:
            deduped[tuple(r.get(k) for k in keys)] = r
        rows = list(deduped.values())

        total = 0
        for i in range(0, len(rows), config.UPSERT_BATCH):
            batch = rows[i:i + config.UPSERT_BATCH]
            resp = self._request(
                "POST", f"{self._base}/{table}",
                params={"on_conflict": on_conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=batch,
            )
            if resp.status_code >= 300:
                raise SupabaseError(
                    f"Upsert {table} gagal [{resp.status_code}]: {resp.text[:500]}"
                )
            total += len(batch)
        return total

    # ── delete where col op value ─────────────────────────────────────────────
    def delete_eq(self, table: str, column: str, value) -> None:
        resp = self._request(
            "DELETE", f"{self._base}/{table}",
            params={column: f"eq.{value}"},
            headers={"Prefer": "return=minimal"},
        )
        if resp.status_code >= 300:
            raise SupabaseError(f"Delete {table} gagal [{resp.status_code}]: {resp.text[:300]}")

    def delete_in(self, table: str, column: str, values: list) -> None:
        """Hapus banyak baris sekaligus: WHERE column IN (values) — per 100 nilai."""
        vals = [v for v in values if v is not None]
        for i in range(0, len(vals), 100):
            chunk = ",".join(str(v) for v in vals[i:i + 100])
            resp = self._request(
                "DELETE", f"{self._base}/{table}",
                params={column: f"in.({chunk})"},
                headers={"Prefer": "return=minimal"},
            )
            if resp.status_code >= 300:
                raise SupabaseError(
                    f"Delete-in {table} gagal [{resp.status_code}]: {resp.text[:300]}")

    # ── select (mis. baca watermark / cek mismatch) ───────────────────────────
    def select(self, table: str, select: str = "*", params: dict | None = None) -> list[dict]:
        q = {"select": select}
        if params:
            q.update(params)
        resp = self._request("GET", f"{self._base}/{table}", params=q)
        if resp.status_code >= 300:
            raise SupabaseError(f"Select {table} gagal [{resp.status_code}]: {resp.text[:300]}")
        return resp.json()

    # ── watermark helpers ─────────────────────────────────────────────────────
    def get_watermark(self, module: str) -> str | None:
        rows = self.select("sync_state", "last_watermark", {"module": f"eq.{module}"})
        return rows[0]["last_watermark"] if rows else None

    def set_watermark(self, module: str, watermark: str) -> None:
        self.upsert("sync_state",
                    [{"module": module, "last_watermark": watermark, "updated_at": utcnow_iso()}],
                    on_conflict="module")

    # ── sync_log ──────────────────────────────────────────────────────────────
    def log_run(self, run_id: str, module: str, status: str, processed: int,
                failed: int, error: str | None, details: dict | None) -> None:
        try:
            self._client.post(f"{self._base}/sync_log",
                              headers={"Prefer": "return=minimal"},
                              json=[{
                                  "run_id": run_id, "module": module, "status": status,
                                  "records_processed": processed, "records_failed": failed,
                                  "error_message": error, "details": details,
                                  "finished_at": utcnow_iso(),
                              }])
        except Exception as e:  # jangan gagalkan sync hanya karena logging
            log.warning(f"Gagal tulis sync_log: {e}")

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
