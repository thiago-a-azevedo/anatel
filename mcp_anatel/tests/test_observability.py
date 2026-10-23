"""Observability contract of the MCP server: structured logs, PII scrubbing,
intent/outcome records and W3C trace-context propagation into the server span."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from src.config import settings
from src.core.logging import GoogleCloudJsonFormatter, PiiRedactionFilter, redact_text
from src.core.observability import summarize_result
from src.main import create_app

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def disable_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_live_http_fetch", False)


@pytest.fixture(scope="module")
def span_exporter() -> InMemorySpanExporter:
    """Installs an in-memory exporter so the SDK's MCP server spans can be inspected."""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def _format(record: logging.LogRecord) -> dict:
    PiiRedactionFilter().filter(record)
    return json.loads(GoogleCloudJsonFormatter().format(record))


def test_json_formatter_emits_cloud_logging_fields_and_extras() -> None:
    record = logging.LogRecord("mcp_anatel.audit", logging.INFO, "x.py", 1, "mcp_tool_outcome", None, None)
    record.event = "mcp_tool_outcome"
    record.latency_ms = 12.5
    payload = _format(record)
    assert payload["severity"] == "INFO"
    assert payload["message"] == "mcp_tool_outcome"
    assert payload["event"] == "mcp_tool_outcome" and payload["latency_ms"] == 12.5
    assert payload["logging.googleapis.com/sourceLocation"]["file"] == "x.py"
    assert "logging.googleapis.com/trace" not in payload  # no active span


def test_json_formatter_correlates_active_span(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_cloud_project", "demo-project")
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("tools/call consultar_rqual_iqs") as span:
        record = logging.LogRecord("mcp_anatel.audit", logging.INFO, "x.py", 1, "msg", None, None)
        payload = _format(record)
    ctx = span.get_span_context()
    assert payload["logging.googleapis.com/trace"] == f"projects/demo-project/traces/{ctx.trace_id:032x}"
    assert payload["logging.googleapis.com/spanId"] == f"{ctx.span_id:016x}"


@pytest.mark.parametrize(
    ("text", "info_type"),
    [
        ("contato joao@example.com", "EMAIL_ADDRESS"),
        ("cpf 123.456.789-09", "BRAZIL_CPF_NUMBER"),
        ("cnpj 12.345.678/0001-95", "BRAZIL_CNPJ_NUMBER"),
        ("tel (11) 98765-4321", "PHONE_NUMBER"),
    ],
)
def test_pii_is_scrubbed_from_message_and_extras(text: str, info_type: str) -> None:
    assert f"[REDACTED_{info_type}]" in redact_text(text)
    record = logging.LogRecord("mcp_anatel.audit", logging.INFO, "x.py", 1, text, None, None)
    record.intended_args = {"termo_busca": text, "nested": [text]}
    payload = _format(record)
    assert text not in json.dumps(payload)
    assert f"[REDACTED_{info_type}]" in payload["message"]
    assert f"[REDACTED_{info_type}]" in payload["intended_args"]["termo_busca"]


def test_pii_filter_keeps_telecom_metrics_intact() -> None:
    text = "IQS 7.85 | 99.9% disponibilidade | latencia 23 ms | 2024-05 | 1.234 reclamacoes"
    assert redact_text(text) == text


def test_summarize_result_reads_rows_and_data_origin() -> None:
    structured = {"registros": [1, 2, 3], "metadados_fonte": {"origem_leitura": "fallback_seed_ram"}}
    assert summarize_result({"isError": False, "structuredContent": structured}) == {
        "status": "success",
        "records_returned": 3,
        "data_origin": "fallback_seed_ram",
    }
    assert summarize_result({"isError": True})["status"] == "error"
    assert summarize_result(None) == {"status": "success", "records_returned": None, "data_origin": None}


async def test_tools_call_logs_intent_and_outcome_and_joins_caller_trace(
    span_exporter: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    """End-to-end over StreamableHTTP: the caller's W3C traceparent (what the ADK MCP
    client injects into ``_meta``) must become the parent of the server span, and the
    middleware must emit a correlated intent/outcome pair."""
    span_exporter.clear()
    caller_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    caller_span_id = "00f067aa0ba902b7"
    payload = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "consultar_rqual_iqs",
            "arguments": {"operadora": "VIVO", "servico": "SCM", "uf": "SP", "limite": 3},
            "_meta": {"traceparent": f"00-{caller_trace_id}-{caller_span_id}-01"},
        },
    }
    with caplog.at_level(logging.INFO, logger="mcp_anatel.audit"):
        app = create_app()  # isolated instance: its session manager can be started once
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.post("/mcp", json=payload, headers=MCP_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["result"].get("isError") is not True

    events = {r.event: r for r in caplog.records if getattr(r, "event", None)}
    assert {"mcp_tool_intent", "mcp_tool_outcome"} <= set(events)
    intent, outcome = events["mcp_tool_intent"], events["mcp_tool_outcome"]
    assert intent.tool == outcome.tool == "consultar_rqual_iqs"
    assert intent.request_id == outcome.request_id == "7"
    assert intent.intended_args["uf"] == "SP"
    assert outcome.status == "success" and outcome.latency_ms >= 0
    assert outcome.records_returned == 3
    assert outcome.data_origin == "fallback_seed_ram"

    server_spans = [s for s in span_exporter.get_finished_spans() if s.name == "tools/call consultar_rqual_iqs"]
    assert server_spans, "the MCP SDK server span must be exported"
    span = server_spans[-1]
    assert f"{span.context.trace_id:032x}" == caller_trace_id
    assert span.parent is not None and f"{span.parent.span_id:016x}" == caller_span_id
    assert span.attributes["anatel.mcp.status"] == "success"
    assert span.attributes["anatel.mcp.records_returned"] == 3
    assert span.attributes["anatel.mcp.data_origin"] == "fallback_seed_ram"
    assert {e.name for e in span.events} >= {"mcp_tool_intent", "mcp_tool_outcome"}
