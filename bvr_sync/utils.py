"""Helper parsing — konversi aman dari string API Jubelio ke tipe Python/JSON."""
from __future__ import annotations
from datetime import datetime, timezone


def to_float(value) -> float | None:
    """'80000.0000' -> 80000.0 ; None/'' -> None."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n", ""):
        return False
    return None


def to_ts(value) -> str | None:
    """Normalisasi timestamp ISO. Jubelio sudah ISO8601, cukup diteruskan.
    Kembalikan None kalau kosong / tak valid supaya kolom timestamptz jadi NULL."""
    if value is None or value == "":
        return None
    s = str(value)
    # Validasi ringan; kalau gagal parse tetap teruskan string aslinya bila menyerupai tanggal.
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s
    except ValueError:
        return s if len(s) >= 8 else None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
