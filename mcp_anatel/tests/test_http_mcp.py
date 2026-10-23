import httpx
import pytest
from src.config import settings
from src.main import app


@pytest.fixture(autouse=True)
def disable_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_live_http_fetch", False)


async def test_health_and_readiness_probes() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp_health = await client.get("/healthz")
        assert resp_health.status_code == 200
        assert resp_health.json()["status"] == "alive"

        resp_ready = await client.get("/readyz")
        assert resp_ready.status_code == 200
        assert resp_ready.json()["status"] == "ready"
        assert resp_ready.json()["fallback_ready"] is True


async def test_streamable_http_mcp_tools_list_and_call() -> None:
    """Exercises the StreamableHTTP protocol on /mcp exactly like Gemini Enterprise
    discovers (tools/list) and runs (tools/call) actions."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            # 1. Action discovery (tools/list) on /mcp without a trailing slash
            list_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
            resp_list = await client.post("/mcp", json=list_payload, headers=headers)
            assert resp_list.status_code == 200
            tools = resp_list.json()["result"]["tools"]
            tool_names = {t["name"] for t in tools}
            expected_tools = {
                "consultar_rqual_iqs",
                "consultar_indicadores_rede",
                "consultar_reclamacoes_ida",
                "consultar_pesquisa_satisfacao",
                "comparar_operadoras",
                "buscar_datasets_ckan_anatel",
                "consultar_glossario_metodologia_anatel",
            }
            assert expected_tools.issubset(tool_names)

            # 2. Action call (tools/call) on /mcp/ (trailing slash, exercising the middleware)
            call_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "comparar_operadoras",
                    "arguments": {"servico": "fibra", "uf": "SP"},
                },
            }
            resp_call = await client.post("/mcp/", json=call_payload, headers=headers)
            assert resp_call.status_code == 200
            result = resp_call.json()["result"]
            assert result.get("isError") is not True
            assert len(result["content"]) > 0
