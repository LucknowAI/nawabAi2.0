"""
Structured JSON logger for production.

Every log record is emitted as a single-line JSON object with fields:
  timestamp, level, service, message, (+ any extras passed via extra={})

Usage:
    from src.utils.util_logger.logger import logger
    logger.info("Event happened", extra={"user_id": 42, "city_id": "delhi"})
"""

import json
import logging
import sys
from datetime import datetime, timezone

from src.config.settings import Settings


class _JsonFormatter(logging.Formatter):
    """Format every log record as a compact JSON line."""

    SERVICE = "nawab-ai"

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.SERVICE,
            "message": record.getMessage(),
        }
        # Forward any extra fields passed via extra={}
        _skip = logging.LogRecord.__dict__.keys() | {
            "message", "asctime", "args", "exc_info", "exc_text", "stack_info",
        }
        for key, val in record.__dict__.items():
            if key not in _skip and not key.startswith("_"):
                payload[key] = val

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def _build_logger() -> logging.Logger:
    log = logging.getLogger("nawab-ai")
    log.setLevel(getattr(logging, Settings.LOG_LEVEL, logging.INFO))
    log.propagate = False

    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        log.addHandler(handler)

    return log


logger = _build_logger()
