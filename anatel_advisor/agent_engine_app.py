"""Agent Runtime entrypoint on Gemini Enterprise Agent Platform (source-based deployment).

Agent Runtime (formerly Vertex AI Agent Engine) imports
``anatel_advisor.agent_engine_app:agent_engine`` from the uploaded source package
(no pickling), so the app is constructed inside the runtime with its own workload identity.
"""

from vertexai.agent_engines import AdkApp

from .agent import app
from .runtime import build_memory_service, build_session_service

agent_engine = AdkApp(
    app=app,
    enable_tracing=True,  # OpenTelemetry spans -> Cloud Trace
    session_service_builder=build_session_service,
    memory_service_builder=build_memory_service,
)
