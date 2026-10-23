"""Long-term memory: PII-safe Agent Platform Memory Bank with non-blocking writes.

* :class:`RedactingMemoryService` wraps any ADK memory service and scrubs PII from
  every event *before* it is sent for memory generation (see :mod:`anatel_advisor.pii`).
* :class:`MemoryPlugin` hooks ``after_run_callback``, which fires once at the end of
  EVERY invocation regardless of which agent answered (coordinator or any
  specialist reached via ``transfer_to_agent``). Memory extraction/consolidation
  on Gemini Enterprise Agent Platform Memory Bank (formerly Vertex AI Memory Bank)
  is an expensive LLM job, so it is fired as a background ``asyncio`` task and the
  user receives the answer immediately.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from google.adk.agents.invocation_context import InvocationContext
from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.plugins.base_plugin import BasePlugin

from .observability.logging import get_logger
from .observability.tracing import get_tracer
from .pii import redact

if TYPE_CHECKING:
    from google.adk.events.event import Event
    from google.adk.sessions.session import Session

logger = get_logger(__name__)
_background_tasks: set[asyncio.Task] = set()


def _redact_event(event: Event) -> Event:
    if not event.content or not event.content.parts:
        return event
    clone = event.model_copy(deep=True)
    for part in clone.content.parts:  # type: ignore[union-attr]
        if part.text:
            part.text = redact(part.text)
    return clone


class RedactingMemoryService(BaseMemoryService):
    """Decorator that redacts PII before delegating to the real memory service."""

    def __init__(self, inner: BaseMemoryService):
        self._inner = inner

    async def add_session_to_memory(self, session: Session) -> None:
        clean = session.model_copy(deep=True)
        clean.events = [_redact_event(e) for e in session.events]
        await self._inner.add_session_to_memory(clean)

    async def add_events_to_memory(self, *, app_name, user_id, events, session_id=None, custom_metadata=None) -> None:
        await self._inner.add_events_to_memory(
            app_name=app_name,
            user_id=user_id,
            events=[_redact_event(e) for e in events],
            session_id=session_id,
            custom_metadata=custom_metadata,
        )

    async def search_memory(self, *, app_name: str, user_id: str, query: str) -> SearchMemoryResponse:
        return await self._inner.search_memory(app_name=app_name, user_id=user_id, query=query)


async def _generate_memories(memory_service: BaseMemoryService, session: Session) -> None:
    with get_tracer().start_as_current_span("anatel.memory.consolidate") as span:
        span.set_attribute("anatel.session.id", session.id)
        span.set_attribute("anatel.session.events", len(session.events))
        try:
            await memory_service.add_session_to_memory(session)
            logger.info(
                "memory_generation_done",
                extra={"session_id": session.id, "user_id": session.user_id, "events": len(session.events)},
            )
        except Exception as exc:  # noqa: BLE001
            span.record_exception(exc)
            logger.warning("memory_generation_failed", extra={"session_id": session.id, "error": str(exc)})


class MemoryPlugin(BasePlugin):
    """Persists every completed invocation to long-term memory, asynchronously."""

    def __init__(self) -> None:
        super().__init__(name="async_memory")

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        memory_service = invocation_context.memory_service
        if memory_service is None:
            return None  # e.g. unit tests or local runs without a memory service
        task = asyncio.create_task(_generate_memories(memory_service, invocation_context.session))
        _background_tasks.add(task)  # strong ref so the task is not garbage-collected
        task.add_done_callback(_background_tasks.discard)
        logger.info(
            "memory_generation_scheduled",
            extra={"session_id": invocation_context.session.id, "invocation_id": invocation_context.invocation_id},
        )
        return None
