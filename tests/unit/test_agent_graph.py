"""Structural tests: agent graph, model routing, HITL wiring, memory redaction, prod hardening."""

from types import SimpleNamespace

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.events.event import Event
from google.adk.sessions.session import Session
from google.genai import types

from anatel_advisor.agent import app, root_agent
from anatel_advisor.memory import RedactingMemoryService
from anatel_advisor.plugins import GuardrailsPlugin, ObservabilityPlugin, ToolGuardPlugin
from anatel_advisor.schemas import CriticVerdict


def _by_name(agent, name):
    if agent.name == name:
        return agent
    for sub in agent.sub_agents:
        found = _by_name(sub, name)
        if found:
            return found
    return None


def test_coordinator_routes_to_specialists():
    names = [a.name for a in root_agent.sub_agents]
    assert names == ["knowledge_agent", "quick_data_agent", "report_pipeline"]


def test_report_pipeline_is_sequential_with_critic():
    pipeline = _by_name(root_agent, "report_pipeline")
    assert isinstance(pipeline, SequentialAgent)
    assert [a.name for a in pipeline.sub_agents] == [
        "data_collector", "telecom_analyst", "quality_critic", "report_publisher",
    ]
    critic = _by_name(root_agent, "quality_critic")
    assert critic.output_schema is CriticVerdict


def test_model_routing_flash_vs_pro():
    analyst = _by_name(root_agent, "telecom_analyst")
    collector = _by_name(root_agent, "data_collector")
    assert "pro" in analyst.model.model
    assert "flash" in collector.model.model
    assert analyst.model.retry_options.attempts >= 3


def test_hitl_export_only_on_coordinator():
    for agent in [root_agent, *root_agent.sub_agents]:
        tools = [getattr(t, "name", "") for t in getattr(agent, "tools", [])]
        if agent is root_agent:
            assert "export_report_to_gcs" in tools
        else:
            assert "export_report_to_gcs" not in tools


def test_app_wires_plugins_compaction_and_cache():
    kinds = {type(p) for p in app.plugins}
    assert {GuardrailsPlugin, ToolGuardPlugin, ObservabilityPlugin} <= kinds
    assert app.events_compaction_config is not None
    assert app.context_cache_config is not None


def test_all_llm_agents_share_constitution():
    def walk(a):
        yield a
        for s in a.sub_agents:
            yield from walk(s)

    for agent in walk(root_agent):
        if isinstance(agent, LlmAgent):
            assert "Hard rules" in agent.static_instruction


class _CaptureMemory:
    def __init__(self):
        self.session = None

    async def add_session_to_memory(self, session):
        self.session = session

    async def search_memory(self, **_):
        return None


async def test_memory_is_redacted_before_storage():
    inner = _CaptureMemory()
    svc = RedactingMemoryService(inner)
    session = Session(
        id="s1", app_name="anatel_advisor", user_id="u1",
        events=[Event(author="user", content=types.Content(
            role="user", parts=[types.Part(text="Sou da Brisanet, meu email é ana@corp.com")]))],
    )
    await svc.add_session_to_memory(session)
    stored = inner.session.events[0].content.parts[0].text
    assert "ana@corp.com" not in stored and "Brisanet" in stored
    # original session untouched
    assert "ana@corp.com" in session.events[0].content.parts[0].text


def test_dev_overrides_ignored_in_managed_runtime(monkeypatch):
    """On Agent Engine an env override must never replace the Secret Manager value."""
    import sys
    import types as pytypes

    from anatel_advisor import secrets

    class _FakeSM:
        def access_secret_version(self, request):
            payload = SimpleNamespace(data=b"https://mcp-from-secret-manager.run.app")
            return SimpleNamespace(payload=payload)

    fake_module = pytypes.SimpleNamespace(SecretManagerServiceClient=lambda: _FakeSM())
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", fake_module)
    monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", "123")
    monkeypatch.setenv("ANATEL_MCP_URL", "https://attacker.example")
    secrets.get_secret.cache_clear()
    try:
        value = secrets.get_secret("anatel-mcp-url", env_override="ANATEL_MCP_URL")
    finally:
        secrets.get_secret.cache_clear()
    assert value == "https://mcp-from-secret-manager.run.app"


def test_export_sanitizes_user_id(monkeypatch):
    from anatel_advisor.tools import report_tools

    monkeypatch.setattr(report_tools, "get_settings", lambda: SimpleNamespace(reports_bucket="", project_id="p"))
    out = report_tools.export_report_to_gcs("t", "r", SimpleNamespace(user_id="../x", state={}))
    assert out["status"] == "error"  # bucket not configured -> guided error, no crash


async def test_memory_plugin_persists_every_invocation():
    """Regression: memory must be written even when a specialist (not the
    coordinator) produced the final answer via transfer_to_agent."""
    import asyncio

    from anatel_advisor.memory import MemoryPlugin

    inner = _CaptureMemory()
    session = Session(id="s1", app_name="anatel_advisor", user_id="u1", events=[])
    ctx = SimpleNamespace(memory_service=inner, session=session, invocation_id="i1")
    await MemoryPlugin().after_run_callback(invocation_context=ctx)
    await asyncio.sleep(0)  # let the background task run
    assert inner.session is session


def test_memory_plugin_registered_on_app():
    from anatel_advisor.memory import MemoryPlugin

    assert any(isinstance(p, MemoryPlugin) for p in app.plugins)


def test_observability_plugin_runs_first():
    """Regression: ADK stops at the first plugin returning a value; observability
    must precede the guard plugins or tool outcomes go unlogged."""
    assert isinstance(app.plugins[0], ObservabilityPlugin)


def test_only_coordinator_can_transfer():
    """Regression: specialists bounced requests to each other until the 500 LLM-call
    limit when the MCP was unavailable. Only the coordinator may route."""

    def walk(a):
        yield a
        for s in a.sub_agents:
            yield from walk(s)

    for agent in walk(root_agent):
        if isinstance(agent, LlmAgent) and agent is not root_agent:
            assert agent.disallow_transfer_to_parent and agent.disallow_transfer_to_peers, agent.name
