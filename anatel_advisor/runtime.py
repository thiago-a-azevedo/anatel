"""Runtime service builders used when the app runs on Agent Runtime (Gemini Enterprise Agent Platform).

Kept in a separate module so ``deployment/deploy.py`` can reference them by import
path (they are cloudpickled by reference and executed inside Agent Runtime).
"""

from __future__ import annotations

import os

from .config import get_settings, is_managed_runtime
from .memory import RedactingMemoryService


def build_memory_service():
    """Gemini Enterprise Agent Platform Memory Bank wrapped with PII redaction."""
    from google.adk.memory import VertexAiMemoryBankService

    settings = get_settings()
    return RedactingMemoryService(
        VertexAiMemoryBankService(
            project=settings.project_id,
            location=settings.location,
            agent_engine_id=os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID"),
        )
    )


def build_session_service():
    """Persistent sessions: SQL database when ``SESSION_SERVICE_URI`` is set locally,
    or managed Agent Platform Sessions (``VertexAiSessionService``) on Agent Runtime.
    """
    db_uri = os.getenv("SESSION_SERVICE_URI")
    if db_uri and not is_managed_runtime():
        from google.adk.sessions import DatabaseSessionService

        return DatabaseSessionService(db_url=db_uri)

    from google.adk.sessions import VertexAiSessionService

    settings = get_settings()
    return VertexAiSessionService(
        project=settings.project_id,
        location=settings.location,
        agent_engine_id=os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID"),
    )
