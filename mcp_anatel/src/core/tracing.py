"""OpenTelemetry distributed tracing for the Anatel MCP server (Cloud Trace).

The MCP Python SDK (2.x) already does two things on its own:

* **Client side** (the ADK agent's ``McpToolset``): every outbound JSON-RPC request is
  wrapped in a ``CLIENT`` span and the W3C ``traceparent`` / ``tracestate`` are injected
  into ``params._meta`` (SEP-414).
* **Server side** (this service): ``mcp.server._otel.OpenTelemetryMiddleware`` is on by
  default and opens a ``SERVER`` span per inbound message (``tools/call <tool>``),
  parented on the ``traceparent`` found in ``_meta``.

Those server spans are **no-ops until a ``TracerProvider`` with an exporter is
installed** - which is what :func:`configure_tracing` does. With it, the Cloud Run hop
shows up inside the same Cloud Trace waterfall as the agent's
``invocation -> agent_run -> execute_tool -> MCP send tools/call`` spans, so a single
request can be followed from the user's question to the Anatel dataset read.

Enablement: ``ENABLE_CLOUD_TRACE=true|false`` (explicit) or automatic when running on
Cloud Run (``K_SERVICE`` is set). Never enabled in unit tests.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import trace

from src import __version__
from src.config import settings

logger = logging.getLogger(__name__)
_CONFIGURED = False


def tracing_enabled() -> bool:
    """True when spans must be exported (explicit flag, or auto on Cloud Run)."""
    if settings.enable_cloud_trace is not None:
        return settings.enable_cloud_trace
    return bool(os.getenv("K_SERVICE"))


def _resource():
    from opentelemetry.sdk.resources import Resource

    attributes: dict[str, Any] = {
        "service.name": settings.otel_service_name,
        "service.version": __version__,
        "deployment.environment": settings.environment,
    }
    if os.getenv("K_SERVICE"):
        attributes.update(
            {
                "cloud.provider": "gcp",
                "cloud.platform": "gcp_cloud_run",
                "faas.name": os.getenv("K_SERVICE", ""),
                "faas.version": os.getenv("K_REVISION", ""),
            }
        )
    resource = Resource.create(attributes)
    if os.getenv("K_SERVICE"):
        try:  # Adds region / project / instance labels from the metadata server.
            from opentelemetry.resourcedetector.gcp import GoogleCloudResourceDetector

            resource = GoogleCloudResourceDetector(raise_on_error=False).detect().merge(resource)
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.debug("gcp_resource_detection_skipped", extra={"error": str(exc)})
    return resource


def configure_tracing() -> None:
    """Registers a Cloud Trace exporter on the global tracer provider (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED or not tracing_enabled():
        return
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=_resource())
        provider.add_span_processor(
            BatchSpanProcessor(
                CloudTraceSpanExporter(project_id=settings.google_cloud_project or None),
                # Cloud Run throttles CPU between requests (request-based billing): a
                # short delay exports most batches while the request still holds CPU;
                # the rest is flushed on the next request or at SIGTERM (atexit shutdown).
                schedule_delay_millis=1000,
            )
        )
        trace.set_tracer_provider(provider)
        _CONFIGURED = True
        logger.info(
            "cloud_trace_enabled",
            extra={"event": "cloud_trace_enabled", "project_id": settings.google_cloud_project},
        )
    except Exception as exc:  # noqa: BLE001 - tracing must never take the service down
        logger.warning("cloud_trace_setup_failed", extra={"error": str(exc)})


def current_trace_context() -> dict[str, Any]:
    """Cloud Logging trace-correlation fields for the active span (empty if none)."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx or not ctx.is_valid:
        return {}
    trace_id = f"{ctx.trace_id:032x}"
    project = settings.google_cloud_project
    return {
        "logging.googleapis.com/trace": f"projects/{project}/traces/{trace_id}" if project else trace_id,
        "logging.googleapis.com/spanId": f"{ctx.span_id:016x}",
        "logging.googleapis.com/trace_sampled": bool(ctx.trace_flags.sampled),
    }
