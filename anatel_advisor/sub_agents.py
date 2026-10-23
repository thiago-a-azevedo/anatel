"""Agent graph: coordinator + specialists + sequential report pipeline.

Topology (Coordinator / Dispatcher pattern + Sequential pipeline + LLM-as-judge)::

    anatel_coordinator (Flash)            routes by intent, owns HITL export
    ├── knowledge_agent (Flash)           glossary / methodology (MCP + Vertex AI Search)
    ├── quick_data_agent (Flash)          single-pillar lookups via MCP
    └── report_pipeline (SequentialAgent)
        ├── data_collector (Flash)        multi-tool MCP retrieval  -> state.collected_data
        ├── telecom_analyst (Pro)         reasoning + custom ranking -> state.analysis_draft
        ├── quality_critic (Flash)        structured self-eval        -> state.critic_verdict
        └── report_publisher (Flash)      applies fixes, final answer -> state.final_report

Each agent gets only the tools it needs (least privilege, smaller prompts).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import VertexAiSearchTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .config import build_model, get_settings
from .prompts import (
    ANALYST_INSTRUCTION,
    COLLECTOR_INSTRUCTION,
    CONSTITUTION,
    CRITIC_INSTRUCTION,
    KNOWLEDGE_INSTRUCTION,
    PUBLISHER_INSTRUCTION,
    QUICK_DATA_INSTRUCTION,
)
from .schemas import CriticVerdict
from .tools.mcp_anatel import (
    ANATEL_DATA_TOOLS,
    build_anatel_toolset,
)
from .tools.report_tools import (
    calculate_weighted_operator_ranking_tool,
    list_supported_anatel_filters_tool,
)

_DETERMINISTIC = types.GenerateContentConfig(temperature=0.1)

# Only the coordinator routes. Specialists answer and hand control back, which makes
# agent-to-agent transfer loops structurally impossible (a failure mode observed when
# a dependency was unavailable: specialists bounced requests until the LLM-call limit).
_NO_TRANSFER = {"disallow_transfer_to_parent": True, "disallow_transfer_to_peers": True}
_ANALYTICAL = types.GenerateContentConfig(temperature=0.3)


def build_knowledge_agent() -> LlmAgent:
    """Explains Anatel concepts using the MCP glossary and, if configured, Vertex AI Search."""
    settings = get_settings()
    tools: list = [build_anatel_toolset(["consultar_glossario_metodologia_anatel",
                                         "buscar_datasets_ckan_anatel"])]
    if settings.vertex_search_datastore:
        tools.append(
            VertexAiSearchTool(
                data_store_id=settings.vertex_search_datastore,
                max_results=5,
                bypass_multi_tools_limit=True,
            )
        )
    return LlmAgent(
        **_NO_TRANSFER,
        name="knowledge_agent",
        description="Explains Anatel regulatory concepts, acronyms (RQUAL, IQS, IDA, ISG, SMP, SCM) and methodology.",
        model=build_model(settings.models.router),
        static_instruction=CONSTITUTION,
        instruction=KNOWLEDGE_INSTRUCTION,
        tools=tools,
        generate_content_config=_DETERMINISTIC,
    )


def build_quick_data_agent() -> LlmAgent:
    """Answers single-pillar factual lookups quickly with Flash."""
    settings = get_settings()
    return LlmAgent(
        **_NO_TRANSFER,
        name="quick_data_agent",
        description="Fast factual lookups of one Anatel indicator for one operator/place (seal, IQS, complaints, satisfaction, network).",
        model=build_model(settings.models.collector),
        static_instruction=CONSTITUTION,
        instruction=QUICK_DATA_INSTRUCTION,
        tools=[PreloadMemoryTool(), build_anatel_toolset(ANATEL_DATA_TOOLS), list_supported_anatel_filters_tool],
        generate_content_config=_DETERMINISTIC,
    )


def build_report_pipeline() -> SequentialAgent:
    """Collect -> analyze -> self-evaluate -> publish."""
    settings = get_settings()

    collector = LlmAgent(
        **_NO_TRANSFER,
        name="data_collector",
        description="Retrieves every Anatel dataset needed for a comparison or report.",
        model=build_model(settings.models.collector),
        static_instruction=CONSTITUTION,
        instruction=COLLECTOR_INSTRUCTION,
        tools=[PreloadMemoryTool(), build_anatel_toolset(ANATEL_DATA_TOOLS), list_supported_anatel_filters_tool],
        output_key="collected_data",
        generate_content_config=_DETERMINISTIC,
    )
    analyst = LlmAgent(
        **_NO_TRANSFER,
        name="telecom_analyst",
        description="Senior analyst that turns collected Anatel data into grounded insights.",
        model=build_model(settings.models.analyst),
        static_instruction=CONSTITUTION,
        instruction=ANALYST_INSTRUCTION,
        tools=[calculate_weighted_operator_ranking_tool],
        output_key="analysis_draft",
        generate_content_config=_ANALYTICAL,
        include_contents="default",
    )
    critic = LlmAgent(
        **_NO_TRANSFER,
        name="quality_critic",
        description="LLM-as-judge that verifies every figure in the draft against tool outputs.",
        model=build_model(settings.models.critic),
        static_instruction=CONSTITUTION,
        instruction=CRITIC_INSTRUCTION,
        output_schema=CriticVerdict,
        output_key="critic_verdict",
        # Sees the raw MCP tool responses in the history (the real ground truth),
        # not only the collector's digest, so correct figures are not rejected.
        include_contents="default",
        generate_content_config=_DETERMINISTIC,
    )
    publisher = LlmAgent(
        **_NO_TRANSFER,
        name="report_publisher",
        description="Applies critic fixes and presents the final grounded report.",
        model=build_model(settings.models.critic),
        static_instruction=CONSTITUTION,
        instruction=PUBLISHER_INSTRUCTION,
        output_key="final_report",
        include_contents="none",
        generate_content_config=_DETERMINISTIC,
    )
    return SequentialAgent(
        name="report_pipeline",
        description="Multi-pillar comparisons, rankings, 'why' analyses and reports with built-in fact-checking.",
        sub_agents=[collector, analyst, critic, publisher],
    )
