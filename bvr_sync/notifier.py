"""Notifikasi WhatsApp — 2 jalur, dicoba berurutan:

  1. Daemon lokal (Baileys, whatsapp/bot.js) — HANYA terjangkau kalau proses
     Python ini jalan di PC yang sama dengan daemon (mis. Task Scheduler
     lokal). Dari GitHub Actions (cloud) jalur ini otomatis gagal-cepat
     (connection refused dalam <1 detik) lalu lanjut ke Fonnte.
  2. Fonnte via Node.js (notify.js) — jalan di mana saja (perlu FONNTE_TOKEN).

Aman gagal — tidak melempar error ke caller.
"""
from __future__ import annotations
import json
import os
import subprocess
import urllib.error
import urllib.request
from . import config
from .logger import get_logger

log = get_logger()

# lokasi notify.js (root proyek, satu level di atas paket bvr_sync)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NOTIFY_JS = os.path.join(_PROJECT_ROOT, "notify.js")


def _send_via_local_wa(message: str) -> bool:
    """Coba kirim lewat daemon whatsapp/bot.js (localhost). Timeout pendek
    supaya tidak memperlambat sync kalau daemon tidak jalan (mis. di cloud)."""
    if not config.WA_GROUP_ID:
        return False
    try:
        body = json.dumps({"to": config.WA_GROUP_ID, "message": message}).encode("utf-8")
        req = urllib.request.Request(
            f"{config.WA_LOCAL_URL}/send", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = resp.status == 200
            if ok:
                log.info("Notifikasi terkirim via WhatsApp lokal (Baileys).")
            return ok
    except (urllib.error.URLError, TimeoutError, ConnectionRefusedError):
        return False  # daemon tidak terjangkau — wajar kalau bukan di PC lokal
    except Exception as e:
        log.warning(f"WA lokal error tak terduga: {e}")
        return False


def send_whatsapp(message: str) -> bool:
    """Kirim pesan: coba daemon WA lokal dulu, lalu fallback Fonnte."""
    if _send_via_local_wa(message):
        return True

    if not config.FONNTE_TOKEN or not config.FONNTE_TARGET:
        log.info("WA lokal tidak terjangkau & Fonnte belum dikonfigurasi — notifikasi dilewati.")
        return False
    if not os.path.exists(_NOTIFY_JS):
        log.warning(f"notify.js tidak ditemukan di {_NOTIFY_JS} — notifikasi dilewati.")
        return False

    node = os.getenv("NODE_EXE", "node")  # set NODE_EXE bila node tidak di PATH
    try:
        proc = subprocess.run(
            [node, _NOTIFY_JS],
            input=message,
            text=True,
            encoding="utf-8",           # aman untuk emoji/newline lintas platform
            capture_output=True,
            timeout=60,
            cwd=_PROJECT_ROOT,
        )
        out = (proc.stdout or "").strip()
        if out:
            log.info(out)
        if proc.returncode != 0:
            err = (proc.stderr or "").strip()
            log.warning(f"notify.js keluar kode {proc.returncode}: {err[:300]}")
            return False
        return True
    except FileNotFoundError:
        log.warning("Node.js tidak ditemukan (node). Set NODE_EXE ke path node.exe. Notifikasi dilewati.")
        return False
    except subprocess.TimeoutExpired:
        log.warning("notify.js timeout — notifikasi dilewati.")
        return False
    except Exception as e:
        log.warning(f"Gagal memanggil notify.js: {e}")
        return False


def notify_success(module: str, processed: int, extra: str = "") -> None:
    send_whatsapp(f"✅ Sync {module.upper()} sukses\n{processed} record diproses.{extra}")


def notify_failure(module: str, error: str) -> None:
    send_whatsapp(f"🚨 Sync {module.upper()} GAGAL\n{error[:600]}")


def notify_unmatched(skus: list[str]) -> None:
    if not skus:
        return
    preview = "\n".join(f"• {s}" for s in skus[:30])
    more = f"\n… dan {len(skus) - 30} SKU lain" if len(skus) > 30 else ""
    send_whatsapp(
        f"⚠️ {len(skus)} SKU di penjualan TIDAK match master produk:\n{preview}{more}"
    )
