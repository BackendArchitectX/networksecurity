from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("request_id", "job_id", "model_version", "drift_status"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_networksecurity_configured", False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root._networksecurity_configured = True  # type: ignore[attr-defined]


configure_logging()
