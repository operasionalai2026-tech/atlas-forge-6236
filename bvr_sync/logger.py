"""Logging terpusat — output ke console + file harian di folder logs/."""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime
from . import config

_configured = False

# Windows console sering cp1252 → emoji di log bisa error. Paksa UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def get_logger(name: str = "bvr_sync") -> logging.Logger:
    global _configured
    logger = logging.getLogger(name)
    if _configured:
        return logger

    os.makedirs(config.LOG_DIR, exist_ok=True)
    logfile = os.path.join(config.LOG_DIR, f"sync_{datetime.now():%Y-%m-%d}.log")

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%H:%M:%S"
    )

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger("bvr_sync")
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(ch)
    root.propagate = False

    _configured = True
    return logger
