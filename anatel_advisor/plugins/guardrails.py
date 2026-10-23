"""Guardrails plugin: input/output safety policy enforced on every model call.

Layered defense:

1. **Google Cloud Model Armor** (when ``MODEL_ARMOR_TEMPLATE`` is set): the user prompt
   is screened with ``SanitizeUserPrompt`` (prompt injection / jailbreak, malicious
   URLs, RAI categories, sensitive data) and the model answer with
   ``SanitizeModelResponse``. The template is provisioned by ``infra/setup.sh``.
2. **Local deterministic rules** (always on, zero latency): prompt-injection phrases
   and a domain allow-list so the assistant stays on Brazilian telecom topics.
3. **Critic self-evaluation** (in the report pipeline, see ``sub_agents.py``): an
   LLM-as-judge checks every number against tool outputs before publishing.

A blocked turn is short-circuited by returning an ``LlmResponse``; the model is never
called and the event is logged as ``guardrail_blocked``.
"""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from ..config import get_settings
from ..observability.logging import get_logger

logger = get_logger(__name__)

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all |the )?(previous|prior|above) (instructions|rules)",
        r"ignore (todas )?(as )?instru[cç][oõ]es (anteriores|acima)",
        r"esque[cç]a (todas )?(as )?(suas )?(regras|instru[cç][oõ]es)",
        r"(reveal|show|print|mostre|revele).{0,30}(system prompt|prompt do sistema|instru[cç][oõ]es internas)",
        r"you are now (dan|developer mode|unfiltered)",
        r"\bjailbreak\b",
    )
]

_BLOCK_MESSAGE = (
    "Não posso ajudar com esse pedido. Sou um assistente especializado em dados públicos "
    "de qualidade e atendimento de telecomunicações da Anatel. Posso, por exemplo, comparar "
    "operadoras, explicar o Selo RQUAL ou analisar reclamações por estado."
)


def _last_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents or []):
        if content.role == "user":
            texts = [p.text for p in (content.parts or []) if p.text]
            if texts:
                return "\n".join(texts)
            return ""  # last user turn is a function response, nothing to screen
    return ""


def detect_prompt_injection(text: str) -> bool:
    """Returns True if ``text`` matches a known prompt-injection pattern."""
    return any(p.search(text) for p in _INJECTION_PATTERNS)


@lru_cache(maxsize=1)
def _model_armor_client():  # pragma: no cover - requires GCP
    from google.cloud import modelarmor_v1

    location = get_settings().location
    return modelarmor_v1.ModelArmorClient(
        client_options={"api_endpoint": f"modelarmor.{location}.rep.googleapis.com"}
    )


def _model_armor_blocks(text: str, *, is_prompt: bool) -> bool:  # pragma: no cover - GCP
    """Screens text with Model Armor. Fails open (logged) if the API is unavailable."""
    template = get_settings().model_armor_template
    if not template or not text:
        return False
    try:
        from google.cloud import modelarmor_v1

        client = _model_armor_client()
        data = modelarmor_v1.DataItem(text=text)
        if is_prompt:
            result = client.sanitize_user_prompt(
                request=modelarmor_v1.SanitizeUserPromptRequest(name=template, user_prompt_data=data)
            )
        else:
            result = client.sanitize_model_response(
                request=modelarmor_v1.SanitizeModelResponseRequest(name=template, model_response_data=data)
            )
        matched = (
            result.sanitization_result.filter_match_state
            == modelarmor_v1.FilterMatchState.MATCH_FOUND
        )
        return matched
    except Exception as exc:  # noqa: BLE001
        logger.warning("model_armor_unavailable", extra={"error": str(exc), "is_prompt": is_prompt})
        return False


def _blocked_response() -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=_BLOCK_MESSAGE)]))


class GuardrailsPlugin(BasePlugin):
    """Screens user input before the model and model output after it."""

    def __init__(self) -> None:
        super().__init__(name="guardrails")
        self._screened_invocations: set[str] = set()

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        # Screen each user message once per invocation (sub-agents reuse the history).
        invocation_id = callback_context.invocation_id
        if invocation_id in self._screened_invocations:
            return None
        text = _last_user_text(llm_request)
        if not text:
            return None
        self._screened_invocations.add(invocation_id)
        if len(self._screened_invocations) > 10_000:
            self._screened_invocations.clear()

        if detect_prompt_injection(text):
            logger.warning(
                "guardrail_blocked",
                extra={"layer": "local_rules", "reason": "prompt_injection", "invocation_id": invocation_id},
            )
            return _blocked_response()
        if await asyncio.to_thread(_model_armor_blocks, text, is_prompt=True):
            logger.warning(
                "guardrail_blocked",
                extra={"layer": "model_armor", "reason": "user_prompt", "invocation_id": invocation_id},
            )
            return _blocked_response()
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        if not llm_response.content or not llm_response.content.parts:
            return None
        text = "\n".join(p.text for p in llm_response.content.parts if p.text and not p.thought)
        if text and await asyncio.to_thread(_model_armor_blocks, text, is_prompt=False):
            logger.warning(
                "guardrail_blocked",
                extra={"layer": "model_armor", "reason": "model_response",
                       "invocation_id": callback_context.invocation_id},
            )
            return _blocked_response()
        return None
