"""Runtime service builders used when the app runs on Vertex AI Agent Engine.

Kept in a separate module so ``deployment/deploy.py`` can reference them by import
path (they are cloudpickled by reference and executed inside Agent Engine).
"""

from __future__ import annotations

import os

from .config import get_settings
from .memory import RedactingMemoryService


def build_memory_service():
    """Vertex AI Memory Bank wrapped with PII redaction."""
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
    """Persistent, managed sessions in Vertex AI Agent Engine."""
    from google.adk.sessions import VertexAiSessionService

    settings = get_settings()
    return VertexAiSessionService(
        project=settings.project_id,
        location=settings.location,
        agent_engine_id=os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID"),
    )
