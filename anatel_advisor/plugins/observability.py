"""Observability plugin: structured *intent vs. outcome* logging for every step.

For each tool call the plugin emits two correlated JSON log records:

* ``tool_intent``  - BEFORE execution: which agent intends to call which tool, with
  which (PII-redacted) arguments, inside which invocation / trace span.
* ``tool_outcome`` - AFTER execution: status, latency, result size, error type and
  whether the result was empty, linked by the same ``call_id``.

The same pattern is applied to the whole invocation (``invocation_start`` /
``invocation_end``), to agent runs (``agent_start`` / ``agent_end``) and to model calls
(``llm_request`` / ``llm_response`` with token usage, or ``llm_error``), so the Cloud
Logging query ``jsonPayload.invocation_id="<id>"`` replays a full request, and the
``logging.googleapis.com/trace`` field jumps straight to the Cloud Trace waterfall.

Message *content* is deliberately never logged (only sizes and counts): the records are
safe to keep long-term, and the PII filter scrubs the few free-text fields (tool args).
"""

from __future__ import annotations

import json
import time
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from opentelemetry import trace

from ..observability.logging import get_logger

logger = get_logger("anatel_advisor.audit")


def _ids(ctx: CallbackContext | ToolContext) -> dict[str, Any]:
    return {
        "invocation_id": getattr(ctx, "invocation_id", None),
        "session_id": getattr(getattr(ctx, "session", None), "id", None),
        "user_id": getattr(ctx, "user_id", None),
        "agent": getattr(ctx, "agent_name", None),
    }


def _invocation_ids(ctx: InvocationContext) -> dict[str, Any]:
    return {
        "invocation_id": getattr(ctx, "invocation_id", None),
        "session_id": getattr(getattr(ctx, "session", None), "id", None),
        "user_id": getattr(ctx, "user_id", None),
        "agent": getattr(getattr(ctx, "agent", None), "name", None),
    }


def _content_chars(content: Any) -> int:
    """Size of a ``types.Content`` in characters (content itself is never logged)."""
    parts = getattr(content, "parts", None) or []
    return sum(len(getattr(p, "text", None) or "") for p in parts)


def _result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"result_type": type(result).__name__}
    structured = result.get("structuredContent") or {}
    registros = structured.get("registros") if isinstance(structured, dict) else None
    return {
        "status": result.get("status") or ("error" if result.get("isError") else "success"),
        "result_chars": len(json.dumps(result, default=str)),
        "records_returned": len(registros) if isinstance(registros, list) else None,
        "data_origin": (structured.get("metadados_fonte") or {}).get("origem_leitura")
        if isinstance(structured, dict)
        else None,
    }


def _tool_call_id(tool: BaseTool, ctx: ToolContext) -> str:
    """Returns a stable correlation id shared by ``before_tool`` and ``after_tool``."""
    return getattr(ctx, "function_call_id", None) or f"{getattr(ctx, 'invocation_id', 'inv')}:{tool.name}"


class ObservabilityPlugin(BasePlugin):
    """Logs intent before and outcome after every invocation, agent, model and tool step."""

    def __init__(self) -> None:
        super().__init__(name="observability")
        self._tool_started: dict[str, float] = {}
        self._agent_started: dict[str, float] = {}
        self._run_started: dict[str, float] = {}

    # ----------------------------------------------------------- invocations
    async def before_run_callback(self, *, invocation_context: InvocationContext):
        if len(self._run_started) > 10_000:
            self._run_started.clear()
        self._run_started[invocation_context.invocation_id] = time.perf_counter()
        logger.info(
            "invocation_start",
            extra={
                "event": "invocation_start",
                "user_message_chars": _content_chars(
                    getattr(invocation_context, "user_content", None)
                ),
                **_invocation_ids(invocation_context),
            },
        )
        return None

    async def after_run_callback(self, *, invocation_context: InvocationContext):
        started = self._run_started.pop(invocation_context.invocation_id, None)
        logger.info(
            "invocation_end",
            extra={
                "event": "invocation_end",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1) if started else None,
                **_invocation_ids(invocation_context),
            },
        )
        return None

    async def on_run_error_callback(
        self, *, invocation_context: InvocationContext, error: Exception
    ):
        started = self._run_started.pop(invocation_context.invocation_id, None)
        logger.error(
            "invocation_error",
            extra={
                "event": "invocation_error",
                "error_type": type(error).__name__,
                "error": str(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1) if started else None,
                **_invocation_ids(invocation_context),
            },
        )
        return None

    # ---------------------------------------------------------------- agents
    async def before_agent_callback(self, *, agent: BaseAgent, callback_context: CallbackContext):
        if len(self._agent_started) > 10_000:
            self._agent_started.clear()
        key = f"{callback_context.invocation_id}:{agent.name}"
        self._agent_started[key] = time.perf_counter()
        logger.info("agent_start", extra={"event": "agent_start", **_ids(callback_context)})
        return None

    async def after_agent_callback(self, *, agent: BaseAgent, callback_context: CallbackContext):
        key = f"{callback_context.invocation_id}:{agent.name}"
        started = self._agent_started.pop(key, None)
        logger.info(
            "agent_end",
            extra={
                "event": "agent_end",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1) if started else None,
                **_ids(callback_context),
            },
        )
        return None

    async def on_agent_error_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext, error: Exception
    ):
        key = f"{callback_context.invocation_id}:{agent.name}"
        started = self._agent_started.pop(key, None)
        logger.error(
            "agent_error",
            extra={
                "event": "agent_error",
                "error_type": type(error).__name__,
                "error": str(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1) if started else None,
                **_ids(callback_context),
            },
        )
        return None

    # ---------------------------------------------------------------- models
    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ):
        logger.info(
            "llm_request",
            extra={
                "event": "llm_request",
                "model": llm_request.model,
                "num_contents": len(llm_request.contents or []),
                "tools_offered": sorted((llm_request.tools_dict or {}).keys()),
                **_ids(callback_context),
            },
        )
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ):
        usage = llm_response.usage_metadata
        planned_calls = [
            p.function_call.name
            for p in ((llm_response.content.parts or []) if llm_response.content else [])
            if p.function_call
        ]
        logger.info(
            "llm_response",
            extra={
                "event": "llm_response",
                "planned_tool_calls": planned_calls,
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "output_tokens": getattr(usage, "candidates_token_count", None),
                "cached_tokens": getattr(usage, "cached_content_token_count", None),
                "error_code": llm_response.error_code,
                **_ids(callback_context),
            },
        )
        return None

    async def on_model_error_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
    ):
        logger.error(
            "llm_error",
            extra={
                "event": "llm_error",
                "model": llm_request.model,
                "error_type": type(error).__name__,
                "error": str(error),
                **_ids(callback_context),
            },
        )
        return None  # let ADK's retry policy / error handling decide

    # ---------------------------------------------------------------- tools
    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ):
        if len(self._tool_started) > 10_000:
            self._tool_started.clear()
        call_id = _tool_call_id(tool, tool_context)
        self._tool_started[call_id] = time.perf_counter()
        span = trace.get_current_span()
        span.set_attribute("anatel.tool.intent", tool.name)
        span.add_event("tool_intent", {"tool": tool.name, "call_id": call_id})
        logger.info(
            "tool_intent",
            extra={
                "event": "tool_intent",
                "call_id": call_id,
                "tool": tool.name,
                "intended_args": tool_args,
                **_ids(tool_context),
            },
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ):
        call_id = _tool_call_id(tool, tool_context)
        started = self._tool_started.pop(call_id, None)
        latency_ms = round((time.perf_counter() - started) * 1000, 1) if started else None
        summary = _result_summary(result)
        span = trace.get_current_span()
        span.set_attribute("anatel.tool.outcome", str(summary.get("status")))
        if latency_ms is not None:
            span.set_attribute("anatel.tool.latency_ms", latency_ms)
        span.add_event(
            "tool_outcome",
            {"tool": tool.name, "call_id": call_id, "status": str(summary.get("status"))},
        )
        logger.info(
            "tool_outcome",
            extra={
                "event": "tool_outcome",
                "call_id": call_id,
                "tool": tool.name,
                "latency_ms": latency_ms,
                **summary,
                **_ids(tool_context),
            },
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ):
        # after_tool_callback still runs afterwards and records the final outcome;
        # here we only capture the raw exception for debugging.
        call_id = _tool_call_id(tool, tool_context)
        started = self._tool_started.get(call_id)
        logger.error(
            "tool_error",
            extra={
                "event": "tool_error",
                "call_id": call_id,
                "tool": tool.name,
                "status": "exception",
                "error_type": type(error).__name__,
                "error": str(error),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1) if started else None,
                **_ids(tool_context),
            },
        )
        return None  # ToolGuardPlugin converts the exception into a recovery hint.
