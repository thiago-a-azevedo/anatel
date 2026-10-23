"""Structured JSON logging for Cloud Logging, with PII scrubbing and trace correlation.

Every record is a single JSON line. Cloud Run / Cloud Logging map the special keys:

* ``severity``                          -> LogEntry.severity
* ``logging.googleapis.com/trace``      -> LogEntry.trace (links the line to its Cloud Trace span)
* ``logging.googleapis.com/spanId``     -> LogEntry.spanId
* ``logging.googleapis.com/sourceLocation`` -> LogEntry.sourceLocation
* every other key (``event``, ``tool``, ``latency_ms`` ...) -> ``jsonPayload``

Before serialization :class:`PiiRedactionFilter` scrubs the message, the formatting
arguments and every ``extra=`` field, so free-text filters forwarded by callers (e.g.
``termo_busca`` or ``municipio``) can never leak e-mails, CPF/CNPJ, phone or card numbers
into the logs. In ``stdio`` mode logs go to stderr so stdout stays a clean MCP channel.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

# Order matters: more specific patterns first (mirrors anatel_advisor/pii.py).
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("BRAZIL_CNPJ_NUMBER", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("BRAZIL_CPF_NUMBER", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("CREDIT_CARD_NUMBER", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    (
        "PHONE_NUMBER",
        re.compile(
            r"(?:\+55\s?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}\b)"
            r"|(?:(?<![\d.])(?:\(?\d{2}\)?\s)?\d{4,5}-\d{4}\b)"
            r"|(?:\(\d{2}\)\s?\d{4,5}\s?\d{4}\b)"
        ),
    ),
]


def redact_text(text: str) -> str:
    """Replaces PII matches with ``[REDACTED_<INFO_TYPE>]``."""
    for info_type, pattern in _PII_PATTERNS:
        text = pattern.sub(f"[REDACTED_{info_type}]", text)
    return text


def redact_obj(value: Any) -> Any:
    """Recursively redacts strings inside dicts / lists (structured log fields)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    return value


class PiiRedactionFilter(logging.Filter):
    """Scrubs PII from the message, the args and every ``extra=`` field."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
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


class GoogleCloudJsonFormatter(logging.Formatter):
    """Formats records as Cloud Logging structured JSON (trace-correlated)."""

    def format(self, record: logging.LogRecord) -> str:
        from src.core.tracing import current_trace_context

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
        # Backwards compatibility: an explicit ``trace_id`` extra wins when no span is active.
        if "logging.googleapis.com/trace" not in payload and getattr(record, "trace_id", None):
            payload["logging.googleapis.com/trace"] = record.trace_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_logging(log_level: str = "INFO", use_stderr: bool = False) -> None:
    """Installs the JSON handler on the root logger.

    ``stdio`` MCP mode must log to stderr so stdout stays a clean JSON-RPC channel;
    on Cloud Run (StreamableHTTP) structured JSON goes to stdout.
    """
    handler = logging.StreamHandler(sys.stderr if use_stderr else sys.stdout)
    handler.setFormatter(GoogleCloudJsonFormatter())
    handler.addFilter(PiiRedactionFilter())
    logging.root.handlers = [handler]
    logging.root.setLevel(log_level.upper())
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
