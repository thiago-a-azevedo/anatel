"""PII redaction for logs and long-term memory.

Two strategies, selected by ``PII_REDACTION_MODE``:

* ``dlp``   - Google Cloud Sensitive Data Protection (DLP) ``deidentify_content`` with
  Brazil-specific info types (CPF, CNPJ) plus email/phone/credit card. Falls back to
  regex if the API call fails, so redaction never silently turns off.
* ``regex`` - Fast local patterns (default; no network, used in tests and CI).
* ``off``   - Disabled (not recommended).

Redaction is applied:

1. to every structured log record (:class:`anatel_advisor.observability.logging.PiiRedactionFilter`);
2. to session events before they are persisted to Vertex AI Memory Bank
   (:class:`anatel_advisor.memory.RedactingMemoryService`).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)

# Order matters: more specific patterns first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("BRAZIL_CNPJ_NUMBER", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("BRAZIL_CPF_NUMBER", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("CREDIT_CARD_NUMBER", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    (
        "PHONE_NUMBER",
        re.compile(r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?(?:9\s?)?\d{4}[-\s]?\d{4}\b"),
    ),
]

_DLP_INFO_TYPES = [
    "BRAZIL_CPF_NUMBER",
    "BRAZIL_CNPJ_NUMBER",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "PERSON_NAME",
]


def redact_regex(text: str) -> str:
    """Replaces PII matches with ``[REDACTED_<INFO_TYPE>]`` using local patterns."""
    for info_type, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED_{info_type}]", text)
    return text


@lru_cache(maxsize=1)
def _dlp_client():  # pragma: no cover - requires GCP
    from google.cloud import dlp_v2

    return dlp_v2.DlpServiceClient()


def redact_dlp(text: str) -> str:  # pragma: no cover - requires GCP
    """Redacts PII through Cloud DLP, falling back to regex on any failure."""
    settings = get_settings()
    try:
        response = _dlp_client().deidentify_content(
            request={
                "parent": f"projects/{settings.project_id}/locations/global",
                "inspect_config": {"info_types": [{"name": t} for t in _DLP_INFO_TYPES]},
                "deidentify_config": {
                    "info_type_transformations": {
                        "transformations": [
                            {"primitive_transformation": {"replace_with_info_type_config": {}}}
                        ]
                    }
                },
                "item": {"value": text},
            }
        )
        return response.item.value
    except Exception as exc:  # noqa: BLE001
        logger.warning("dlp_redaction_failed_fallback_regex", extra={"error": str(exc)})
        return redact_regex(text)


def redact(text: str | None) -> str | None:
    """Redacts PII from ``text`` according to the configured mode."""
    if not text:
        return text
    mode = get_settings().pii_redaction_mode.lower()
    if mode == "off":
        return text
    if mode == "dlp":
        return redact_dlp(text)
    return redact_regex(text)


def redact_obj(value: Any) -> Any:
    """Recursively redacts strings inside dicts/lists (used for structured log fields)."""
    if isinstance(value, str):
        return redact_regex(value)  # always local for high-volume structured fields
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    return value
