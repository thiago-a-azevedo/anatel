"""OpenTelemetry distributed tracing exported to Google Cloud Trace.

ADK already instruments every invocation, agent run, LLM call and tool call as
OpenTelemetry spans (``invocation`` -> ``agent_run`` -> ``call_llm`` / ``execute_tool``).
This module wires those spans to Cloud Trace so a request can be followed end-to-end
from the user query to the final answer, including the HTTP hop to the Anatel MCP
server.

* On Vertex AI Agent Engine, tracing is enabled with ``AdkApp(enable_tracing=True)``
  (see ``deployment/deploy.py``) and this module is a no-op.
* Locally / in CI, set ``ENABLE_CLOUD_TRACE=true`` to export spans to Cloud Trace.
"""

from __future__ import annotations

import logging

from opentelemetry import trace

from ..config import get_settings

logger = logging.getLogger(__name__)
_CONFIGURED = False

TRACER_NAME = "anatel_advisor"


def configure_tracing() -> None:
    """Registers a Cloud Trace exporter on the global tracer provider (idempotent)."""
    global _CONFIGURED
    settings = get_settings()
    if _CONFIGURED or not settings.enable_cloud_trace:
        return
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.app_name})
        )
        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.project_id))
        )
        trace.set_tracer_provider(provider)
        _CONFIGURED = True
        logger.info("cloud_trace_enabled", extra={"project_id": settings.project_id})
    except Exception as exc:  # noqa: BLE001
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
