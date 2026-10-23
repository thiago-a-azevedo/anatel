"""Agent Runtime entrypoint on Gemini Enterprise Agent Platform (source-based deployment).

Agent Runtime (formerly Vertex AI Agent Engine) imports
``anatel_advisor.agent_engine_app:agent_engine`` from the uploaded source package
(no pickling), so the app is constructed inside the runtime with its own workload identity.

Telemetry is switched on through the runtime environment variable
``GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`` (set by ``deployment/deploy.py``)
instead of the legacy ``AdkApp(enable_tracing=True)`` flag:

* it enables OpenTelemetry **traces, logs and metrics** export to Google Cloud
  Observability (Cloud Trace / Cloud Logging / Cloud Monitoring) and keeps the Cloud
  Console telemetry toggle authoritative;
* unlike ``enable_tracing=True`` it does **not** force
  ``ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true``, so prompts, model responses and tool
  arguments never land in span attributes (PII stays out of Cloud Trace). Intent and
  outcome are recorded by :class:`anatel_advisor.plugins.ObservabilityPlugin` as
  PII-redacted structured logs instead.
"""

from vertexai.agent_engines import AdkApp

from .agent import app
from .runtime import build_memory_service, build_session_service

agent_engine = AdkApp(
    app=app,
    session_service_builder=build_session_service,
    memory_service_builder=build_memory_service,
)
