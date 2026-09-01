from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

_CONFIGURED = False
_LOG_PATH = Path(__file__).resolve().parents[3] / "logs" / "max.trace.log"


def _ensure_logger() -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("messager.max")
    if _CONFIGURED:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = True
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
    _CONFIGURED = True
    return logger


def max_trace(message: str, *args: object) -> None:
    """Always-visible Max diagnostics: stderr + logs/max.trace.log."""
    text = message % args if args else message
    stamp = time.strftime("%H:%M:%S")
    sys.stderr.write(f"{stamp} [MAX] {text}\n")
    sys.stderr.flush()
    _ensure_logger().info(text)
