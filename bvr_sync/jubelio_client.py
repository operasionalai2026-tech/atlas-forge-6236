"""Client Jubelio — login, GET dengan retry + backoff + penanganan 429.

Dipakai oleh modul orders & products. Sengaja sinkron + jeda kecil antar
request supaya tidak kena rate limit (API Jubelio mudah balas 429).
"""
from __future__ import annotations
import time
import httpx
from . import config
from .logger import get_logger

log = get_logger()


class JubelioError(Exception):
    pass


class JubelioClient:
    def __init__(self):
        self._client = httpx.Client(timeout=60)
        self._token: str | None = None

    # ── login ────────────────────────────────────────────────────────────────
    def login(self) -> str:
        resp = self._client.post(
            config.JUBELIO_LOGIN_URL,
            json={"email": config.JUBELIO_EMAIL, "password": config.JUBELIO_PASSWORD},
        )
        resp.raise_for_status()
        token = resp.json().get("token")
        if not token:
            raise JubelioError("Login Jubelio gagal: token tidak ditemukan di response.")
        self._token = token
        log.info("Login Jubelio berhasil.")
        return token

    @property
    def _headers(self) -> dict:
        if not self._token:
            self.login()
        return {"Authorization": self._token}

    # ── GET dengan retry ──────────────────────────────────────────────────────
    def get(self, path: str, params: dict | None = None) -> dict:
        url = config.JUBELIO_BASE_URL.rstrip("/") + path
        delay = config.REQUEST_DELAY_MS / 1000.0
        backoff = 1.5

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                resp = self._client.get(url, headers=self._headers, params=params)
                if resp.status_code == 429:
                    wait = backoff ** attempt + 1
                    log.warning(f"429 rate-limit di {path} — tunggu {wait:.1f}s (percobaan {attempt})")
                    time.sleep(wait)
                    continue
                if resp.status_code == 401:
                    log.warning("Token kedaluwarsa — login ulang.")
                    self._token = None
                    self.login()
                    continue
                resp.raise_for_status()
                time.sleep(delay)  # jeda sopan antar request sukses
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == config.MAX_RETRIES:
                    raise JubelioError(f"GET {path} gagal setelah {attempt}x: {e}") from e
                time.sleep(backoff ** attempt)
            except httpx.RequestError as e:
                if attempt == config.MAX_RETRIES:
                    raise JubelioError(f"GET {path} error jaringan setelah {attempt}x: {e}") from e
                time.sleep(backoff ** attempt)
        raise JubelioError(f"GET {path} gagal (habis retry).")

    # ── helper spesifik ───────────────────────────────────────────────────────
    def list_orders(self, page: int, page_size: int) -> dict:
        return self.get(
            config.ORDERS_PATH,
            params={
                "page": page,
                "pageSize": page_size,
                "sortBy": "last_modified",
                "sortDirection": "DESC",
            },
        )

    def get_order_detail(self, salesorder_id: int) -> dict:
        return self.get(f"{config.ORDER_DETAIL_PATH}{salesorder_id}")

    def list_inventory(self, page: int, page_size: int) -> dict:
        return self.get(
            config.INVENTORY_PATH,
            params={"page": page, "page_size": page_size, "sort_direction": "NONE"},
        )

    def list_masters(self, page: int, page_size: int) -> dict:
        """Daftar produk master (halaman Product Master di v2.jubelio.com)."""
        return self.get(
            config.MASTERS_PATH,
            params={
                "page": page,
                "page_size": page_size,
                "sort_by": "last_modified",
                "sort_direction": "DESC",
                "bundle_filter": config.BUNDLE_FILTER,
            },
        )

    def get_catalog(self, item_group_id: int) -> dict:
        """Detail 1 master: berat, kategori, brand, variasi, daftar SKU."""
        return self.get(
            f"{config.CATALOG_PATH}{item_group_id}",
            params={"isMaster": "true", "isArchived": "false"},
        )

    def list_preorder(self, page: int, page_size: int) -> dict:
        """PO/Inbound stock yang belum dipenuhi."""
        return self.get(
            "/inventory/v2/inbound-purchase-not-fulfilled/",
            params={
                "page": page,
                "page_size": page_size,
                "sort_by": "item_name",
                "sort_direction": "ASC",
            },
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
