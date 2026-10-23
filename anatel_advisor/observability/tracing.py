"""OpenTelemetry distributed tracing exported to Google Cloud Observability.

ADK already instruments every invocation, agent run, LLM call and tool call as
OpenTelemetry spans (``invocation`` -> ``agent_run`` -> ``call_llm`` / ``execute_tool``),
and the MCP client it uses wraps each ``tools/call`` in a ``CLIENT`` span whose W3C
``traceparent`` is propagated to the Anatel MCP server (``mcp_anatel/``), which
continues the same trace on Cloud Run. This module wires those spans to Cloud Trace so a
request can be followed end-to-end from the user query to the Anatel dataset read.

* On Agent Runtime (Gemini Enterprise Agent Platform) telemetry is enabled by the
  runtime itself through ``GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`` (set by
  ``deployment/deploy.py``): traces, logs and metrics are exported via OTLP to
  Google Cloud Observability and this module is a no-op.
* Locally / in CI, set ``ENABLE_CLOUD_TRACE=true`` to export with the same ADK
  helpers (``google.adk.telemetry``): Cloud Trace + Cloud Logging + Cloud Monitoring
  (GenAI token / latency metrics). Equivalent to ``adk web --otel_to_cloud``.

Privacy defaults (both environments): message content is **not** copied into span
attributes or GenAI events (``ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`` /
``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`` default to ``false`` here);
intent and outcome are logged, PII-redacted, by ``plugins/observability.py``.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace

from ..config import get_settings

logger = logging.getLogger(__name__)
_CONFIGURED = False

TRACER_NAME = "anatel_advisor"

#: Env vars that decide whether prompts / responses / tool args are copied into telemetry,
#: with their privacy-preserving defaults (legacy ADK spans and OTel GenAI semconv).
CONTENT_CAPTURE_DEFAULTS: dict[str, str] = {
    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "NO_CONTENT",
}
CONTENT_CAPTURE_ENV_VARS = tuple(CONTENT_CAPTURE_DEFAULTS)


def apply_privacy_defaults() -> None:
    """Keeps message content out of spans/events unless an operator opts in explicitly."""
    for name, value in CONTENT_CAPTURE_DEFAULTS.items():
        os.environ.setdefault(name, value)


def _configure_with_adk(settings) -> bool:
    """Traces + metrics + logs through ADK's own Google Cloud exporters (OTLP)."""
    from google.adk.telemetry.google_cloud import get_gcp_exporters
    from google.adk.telemetry.setup import maybe_set_otel_providers
    from opentelemetry.sdk.resources import Resource

    os.environ.setdefault("OTEL_SERVICE_NAME", settings.app_name)
    hooks = get_gcp_exporters(
        enable_cloud_tracing=True, enable_cloud_metrics=True, enable_cloud_logging=True
    )
    if not hooks.span_processors:
        return False
    maybe_set_otel_providers(
        otel_hooks_to_setup=[hooks],
        otel_resource=Resource.create({"service.name": settings.app_name}),
    )
    return True


def _configure_cloud_trace_only(settings) -> None:
    """Fallback: spans only, through the Cloud Trace exporter."""
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": settings.app_name}))
    provider.add_span_processor(
        BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.project_id))
    )
    trace.set_tracer_provider(provider)


def configure_tracing() -> None:
    """Registers Google Cloud exporters on the global OTel providers (idempotent)."""
    global _CONFIGURED
    apply_privacy_defaults()
    settings = get_settings()
    if _CONFIGURED or not settings.enable_cloud_trace:
        return
    try:
        signals = "traces+metrics+logs" if _configure_with_adk(settings) else None
        if signals is None:
            _configure_cloud_trace_only(settings)
            signals = "traces"
        _CONFIGURED = True
        logger.info(
            "cloud_observability_enabled",
            extra={"project_id": settings.project_id, "signals": signals},
        )
    except Exception as exc:  # noqa: BLE001 - telemetry must never break the agent
        logger.warning("cloud_trace_setup_failed", extra={"error": str(exc)})


def get_tracer() -> trace.Tracer:
    """Returns the application tracer."""
    return trace.get_tracer(TRACER_NAME)


def current_trace_context() -> dict[str, str]:
    """Returns Cloud Logging trace-correlation fields for the active span, if any."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return {}
    project = get_settings().project_id
    return {
        "logging.googleapis.com/trace": f"projects/{project}/traces/{ctx.trace_id:032x}",
        "logging.googleapis.com/spanId": f"{ctx.span_id:016x}",
        "logging.googleapis.com/trace_sampled": bool(ctx.trace_flags.sampled),
    }
