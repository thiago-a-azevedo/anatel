"""Root agent and ADK ``App`` for the Anatel Telecom Advisor.

``root_agent`` is discovered by ``adk web`` / ``adk run``; ``app`` bundles the agent with
plugins (guardrails, tool guard, observability), history compaction and context
caching, and is what gets deployed to Agent Runtime on Gemini Enterprise Agent Platform
(formerly Vertex AI Agent Engine).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .config import build_model, get_settings
from .memory import MemoryPlugin
from .observability import configure_logging, configure_tracing
from .plugins import GuardrailsPlugin, ObservabilityPlugin, ToolGuardPlugin
from .prompts import CONSTITUTION, COORDINATOR_INSTRUCTION
from .sub_agents import build_knowledge_agent, build_quick_data_agent, build_report_pipeline
from .tools.report_tools import export_report_to_gcs_tool

configure_logging()
configure_tracing()

settings = get_settings()

root_agent = LlmAgent(
    name="anatel_coordinator",
    description="Entry point: classifies the request and delegates to the right specialist.",
    model=build_model(settings.models.router),
    static_instruction=CONSTITUTION,
    instruction=COORDINATOR_INSTRUCTION,
    tools=[PreloadMemoryTool(), export_report_to_gcs_tool],
    sub_agents=[build_knowledge_agent(), build_quick_data_agent(), build_report_pipeline()],
    generate_content_config=types.GenerateContentConfig(temperature=0.1),
)

app = App(
    name=settings.app_name,
    root_agent=root_agent,
    # Order matters: ADK stops at the first plugin that returns a value. The
    # observability plugin never returns one, so it goes FIRST to see every call
    # (including calls short-circuited or rewritten by the guard plugins).
    plugins=[ObservabilityPlugin(), GuardrailsPlugin(), ToolGuardPlugin(), MemoryPlugin()],
    # Context-bloat management: every N invocations older events are summarized by
    # Flash into a single compacted event (sliding window with overlap).
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=settings.compaction_interval,
        overlap_size=settings.compaction_overlap,
        summarizer=LlmEventSummarizer(llm=build_model(settings.models.summarizer)),
    ),
    # Gemini context caching for the large, static constitution + tool declarations.
    context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
)
