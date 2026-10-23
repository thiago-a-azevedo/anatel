"""Tool guard plugin: schema validation and guided error recovery for tool calls.

* ``before_tool_callback`` validates arguments sent to the remote MCP tools against
  the Pydantic schemas in :mod:`anatel_advisor.schemas`. Invalid calls are
  short-circuited (no network round-trip) and the LLM receives a precise
  ``recovery_hint`` (e.g. "Invalid UF 'Sao Paulo'. Use the 2-letter code ...").
  Valid calls get their arguments normalized (``'banda larga'`` -> ``'SCM'``).
* ``after_tool_callback`` detects semantically empty or failed MCP results and
  appends recovery guidance so the model broadens filters instead of hallucinating.
* ``on_tool_error_callback`` turns exceptions (timeouts, 401/403, connection errors)
  into structured error payloads instead of crashing the run.
"""

from __future__ import annotations

from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from ..observability.logging import get_logger
from ..schemas import MCP_ARG_SCHEMAS

logger = get_logger(__name__)


def _validation_hint(tool_name: str, exc: ValidationError) -> dict[str, Any]:
    problems = [
        f"{'.'.join(str(p) for p in err['loc']) or 'args'}: {err['msg']}" for err in exc.errors()
    ]
    return {
        "status": "error",
        "error_type": "invalid_arguments",
        "tool": tool_name,
        "error_message": "; ".join(problems),
        "recovery_hint": (
            "Fix the arguments and call the tool again. If unsure about valid values, "
            "call list_supported_anatel_filters first. Do not invent data."
        ),
    }


def _recovery_for_exception(error: Exception) -> str:
    text = f"{type(error).__name__}: {error}".lower()
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        return (
            "The Anatel data service rejected the credentials. Do not retry. Tell the user "
            "the data source is temporarily unavailable."
        )
    if "timeout" in text or "timed out" in text:
        return (
            "The Anatel data service timed out. Retry ONCE with a narrower query (add uf, "
            "servico or a lower limite). If it fails again, tell the user."
        )
    if "connect" in text or "unavailable" in text or "503" in text:
        return "The Anatel data service is unreachable. Retry once; if it fails, tell the user."
    return "Unexpected tool failure. Do not retry with the same arguments; explain the limitation."


class ToolGuardPlugin(BasePlugin):
    """Validates tool arguments and converts failures into actionable guidance."""

    def __init__(self) -> None:
        super().__init__(name="tool_guard")

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ):
        schema = MCP_ARG_SCHEMAS.get(tool.name)
        if schema is None:
            return None
        try:
            validated = schema.model_validate(tool_args)
        except ValidationError as exc:
            logger.warning(
                "tool_args_rejected",
                extra={"tool": tool.name, "args": tool_args, "errors": exc.errors(include_url=False)},
            )
            return _validation_hint(tool.name, exc)
        # Normalize in place so the MCP server receives canonical values.
        tool_args.clear()
        tool_args.update(validated.model_dump(exclude_none=True))
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ):
        if tool.name not in MCP_ARG_SCHEMAS or not isinstance(result, dict):
            return None
        if result.get("isError"):
            return {
                **result,
                "recovery_hint": (
                    "The Anatel tool returned an error. Read the message, adjust the "
                    "arguments (uf, servico, operadora, ano_mes) and retry once."
                ),
            }
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and structured.get("registros") == []:
            return {
                **result,
                "recovery_hint": (
                    "No records matched these filters. Broaden the query: drop municipio, "
                    "drop ano_mes, or use uf='BR'. Never fabricate numbers for empty results."
                ),
            }
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ):
        return {
            "status": "error",
            "error_type": type(error).__name__,
            "tool": tool.name,
            "error_message": str(error)[:500],
            "recovery_hint": _recovery_for_exception(error),
        }
