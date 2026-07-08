"""Client Jubelio — login, GET dengan retry + backoff + throttle ADAPTIF.

Strategi anti rate-limit:
  - Jeda antar request menyesuaikan diri: mulai dari REQUEST_DELAY_MS,
    turun pelan saat lancar (sampai REQUEST_DELAY_MIN_MS), naik tajam saat
    kena 429 (sampai REQUEST_DELAY_MAX_MS).
  - 429 menghormati header Retry-After bila ada.
  - 5xx / error jaringan di-retry dengan backoff eksponensial + jitter.
"""
from __future__ import annotations
import random
import time
import httpx
from . import config
from .logger import get_logger

log = get_logger()


class JubelioError(Exception):
    pass


class _AdaptiveThrottle:
    """Atur jeda antar request berdasarkan respons server."""

    def __init__(self):
        self.delay = config.REQUEST_DELAY_MS / 1000.0
        self.min_d = config.REQUEST_DELAY_MIN_MS / 1000.0
        self.max_d = config.REQUEST_DELAY_MAX_MS / 1000.0
        self._clean_streak = 0

    def wait(self):
        # jitter ±20% supaya pola request tidak seragam (lebih ramah limiter)
        time.sleep(self.delay * random.uniform(0.8, 1.2))

    def on_success(self):
        self._clean_streak += 1
        if self._clean_streak >= 20:            # 20 request mulus → percepat 10%
            self.delay = max(self.min_d, self.delay * 0.9)
            self._clean_streak = 0

    def on_rate_limited(self):
        self._clean_streak = 0
        self.delay = min(self.max_d, max(self.delay, 0.2) * 1.6)
        log.info(f"Throttle dinaikkan ke {self.delay*1000:.0f}ms/request.")


class JubelioClient:
    def __init__(self):
        self._client = httpx.Client(
            timeout=60,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._token: str | None = None
        self._throttle = _AdaptiveThrottle()

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

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                self._throttle.wait()
                resp = self._client.get(url, headers=self._headers, params=params)

                if resp.status_code == 429:
                    self._throttle.on_rate_limited()
                    # hormati Retry-After bila server memberi tahu
                    retry_after = resp.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else 0.0
                    except ValueError:
                        wait = 0.0
                    wait = max(wait, 1.6 ** attempt + random.uniform(0, 1))
                    log.warning(f"429 rate-limit di {path} — tunggu {wait:.1f}s (percobaan {attempt})")
                    time.sleep(wait)
                    continue

                if resp.status_code == 401:
                    log.warning("Token kedaluwarsa — login ulang.")
                    self._token = None
                    self.login()
                    continue

                if resp.status_code >= 500:      # transient server error → retry
                    wait = 1.6 ** attempt + random.uniform(0, 1)
                    log.warning(f"{resp.status_code} di {path} — retry dalam {wait:.1f}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                self._throttle.on_success()
                return resp.json()

            except httpx.HTTPStatusError as e:
                if attempt == config.MAX_RETRIES:
                    raise JubelioError(f"GET {path} gagal setelah {attempt}x: {e}") from e
                time.sleep(1.6 ** attempt + random.uniform(0, 1))
            except httpx.RequestError as e:
                if attempt == config.MAX_RETRIES:
                    raise JubelioError(f"GET {path} error jaringan setelah {attempt}x: {e}") from e
                time.sleep(1.6 ** attempt + random.uniform(0, 1))
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

    def list_returns(self, page: int, page_size: int) -> dict:
        """Retur penjualan (credit note online), sort last_modified DESC."""
        return self.get(
            "/sales/sales-returns/",
            params={
                "page": page,
                "pageSize": page_size,
                "sortBy": "last_modified",
                "sortDirection": "DESC",
            },
        )

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
