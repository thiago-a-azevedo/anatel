"""Long-term memory: PII-safe Vertex AI Memory Bank with non-blocking writes.

* :class:`RedactingMemoryService` wraps any ADK memory service and scrubs PII from
  every event *before* it is sent for memory generation (see :mod:`anatel_advisor.pii`).
* :func:`schedule_memory_generation` is used as the root agent's
  ``after_agent_callback``: memory extraction/consolidation on Memory Bank is an
  expensive LLM job, so it is fired as a background ``asyncio`` task and the user
  receives the answer immediately.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from google.adk.agents.callback_context import CallbackContext
from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse

from .observability.logging import get_logger
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


async def _generate_memories(callback_context: CallbackContext) -> None:
    try:
        await callback_context.add_session_to_memory()
        logger.info(
            "memory_generation_done",
            extra={"session_id": callback_context.session.id, "user_id": callback_context.user_id},
        )
    except ValueError:
        pass  # No memory service configured (e.g. unit tests).
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_generation_failed", extra={"error": str(exc)})


async def schedule_memory_generation(callback_context: CallbackContext) -> None:
    """``after_agent_callback`` that persists the session to memory asynchronously.

    Returns ``None`` immediately so the response is never delayed by memory
    extraction. A strong reference to the task is kept to avoid garbage collection.
    """
    task = asyncio.create_task(_generate_memories(callback_context))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return None
