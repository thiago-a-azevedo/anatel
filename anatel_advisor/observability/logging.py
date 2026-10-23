"""Structured JSON logging compatible with Google Cloud Logging.

Each record is emitted as a single JSON line on stdout. Cloud Logging (Agent Engine,
Cloud Run, GKE) parses these lines automatically and maps:

* ``severity``                         -> LogEntry.severity
* ``logging.googleapis.com/trace``     -> LogEntry.trace (links logs to Cloud Trace spans)
* ``logging.googleapis.com/spanId``    -> LogEntry.spanId
* every other key                      -> jsonPayload

All string fields are scrubbed by :class:`PiiRedactionFilter` before serialization.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from ..config import get_settings
from ..pii import redact_obj, redact_regex

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
_CONFIGURED = False


class PiiRedactionFilter(logging.Filter):
    """Scrubs PII from the message, formatting args and every ``extra=`` field."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            record.msg = redact_regex(record.msg)
        if record.args:
            record.args = (
                tuple(redact_obj(a) for a in record.args)
                if isinstance(record.args, tuple)
                else redact_obj(record.args)
            )
        for key, value in list(vars(record).items()):
            if key not in _RESERVED:
                setattr(record, key, redact_obj(value))
        return True


class CloudJsonFormatter(logging.Formatter):
    """Formats records as Cloud Logging structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        from .tracing import current_trace_context

        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "logger": record.name,
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }
        payload.update(current_trace_context())
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Installs the JSON handler on the root logger (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudJsonFormatter())
    handler.addFilter(PiiRedactionFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(get_settings().log_level.upper())
    # Quiet noisy libraries.
    for noisy in ("httpx", "httpcore", "urllib3", "google.auth", "grpc"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Returns a logger, ensuring structured logging is configured."""
    configure_logging()
    return logging.getLogger(name)
