"""Centralized runtime configuration for the Anatel Telecom Advisor.

All values come from environment variables (12-factor). Sensitive values are never
hardcoded: they are resolved at runtime from Google Secret Manager via
:mod:`anatel_advisor.secrets` (see ``Settings.mcp_server_url``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelRouting:
    """Strategic model routing table.

    Each agent role is mapped to the cheapest model that can do the job well:

    * ``router`` / ``collector`` / ``critic``: latency-sensitive, short-context work
      (intent classification, tool calling, rubric checks) -> Flash.
    * ``analyst``: multi-source reasoning, weighting and narrative synthesis -> Pro.
    * ``summarizer``: history compaction runs in the background -> Flash.
    """

    router: str = field(default_factory=lambda: os.getenv("MODEL_ROUTER", "gemini-2.5-flash"))
    collector: str = field(default_factory=lambda: os.getenv("MODEL_COLLECTOR", "gemini-2.5-flash"))
    analyst: str = field(default_factory=lambda: os.getenv("MODEL_ANALYST", "gemini-2.5-pro"))
    critic: str = field(default_factory=lambda: os.getenv("MODEL_CRITIC", "gemini-2.5-flash"))
    summarizer: str = field(
        default_factory=lambda: os.getenv("MODEL_SUMMARIZER", "gemini-2.5-flash")
    )


@dataclass(frozen=True)
class Settings:
    """Typed view over environment variables."""

    project_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    location: str = field(
        default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "anatel_advisor"))

    # MCP server: URL is resolved from Secret Manager (secret id below) with an
    # optional env override for local development.
    mcp_url_secret_id: str = field(
        default_factory=lambda: os.getenv("MCP_URL_SECRET_ID", "anatel-mcp-url")
    )
    mcp_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("MCP_TIMEOUT_SECONDS", "30"))
    )

    # Reports (HITL-protected export).
    reports_bucket: str = field(default_factory=lambda: os.getenv("REPORTS_BUCKET", ""))

    # Knowledge base (Agent Search on Gemini Enterprise Agent Platform, formerly Vertex AI Search).
    vertex_search_datastore: str = field(
        default_factory=lambda: (
            os.getenv("AGENT_SEARCH_DATASTORE") or os.getenv("VERTEX_SEARCH_DATASTORE", "")
        )
    )

    # Guardrails.
    model_armor_template: str = field(
        default_factory=lambda: os.getenv("MODEL_ARMOR_TEMPLATE", "")
    )
    # "open": allow the turn if Model Armor is unreachable (logged as warning).
    # "closed": block the turn if Model Armor is unreachable (strictest).
    guardrails_fail_mode: str = field(
        default_factory=lambda: os.getenv("GUARDRAILS_FAIL_MODE", "open").lower()
    )

    # Observability.
    pii_redaction_mode: str = field(
        default_factory=lambda: os.getenv("PII_REDACTION_MODE", "regex")
    )  # one of: regex | dlp | off
    enable_cloud_trace: bool = field(
        default_factory=lambda: _env_bool("ENABLE_CLOUD_TRACE", False)
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Context management.
    compaction_interval: int = field(
        default_factory=lambda: int(os.getenv("COMPACTION_INTERVAL", "6"))
    )
    compaction_overlap: int = field(
        default_factory=lambda: int(os.getenv("COMPACTION_OVERLAP", "1"))
    )

    models: ModelRouting = field(default_factory=ModelRouting)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the process-wide settings singleton."""
    return Settings()


def is_managed_runtime() -> bool:
    """True when running on Agent Runtime on Gemini Enterprise Agent Platform (or Cloud Run).

    Used to disable developer-only fallbacks (env-provided tokens, gcloud CLI) in
    production so the workload identity is the only credential path.
    """
    return bool(os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID") or os.getenv("K_SERVICE"))


def build_model(model_name: str):
    """Returns a Gemini model with exponential-backoff retries on 429/5xx.

    Retries make the agent resilient to transient quota/availability errors
    instead of failing the whole multi-agent run.
    """
    from google.adk.models import Gemini
    from google.genai import types

    return Gemini(
        model=model_name,
        retry_options=types.HttpRetryOptions(
            attempts=4,
            initial_delay=1.0,
            max_delay=20.0,
            exp_base=2.0,
            http_status_codes=[408, 429, 500, 502, 503, 504],
        ),
    )
