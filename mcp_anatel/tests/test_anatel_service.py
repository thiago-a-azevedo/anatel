import pytest
from src.application.anatel_service import anatel_service
from src.config import settings
from src.infrastructure.memory_cache import memory_cache


@pytest.fixture(autouse=True)
def disable_external_http_in_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garante execução instantânea e determinística em memória nos testes automatizados."""
    monkeypatch.setattr(settings, "enable_live_http_fetch", False)
    memory_cache.clear()


async def test_consultar_rqual_iqs_por_operadora_e_uf() -> None:
    res = await anatel_service.consultar_rqual_iqs(
        operadora="Telefonica",
        servico="fibra",
        uf="São Paulo",
    )
    assert res["metadados_fonte"]["filtros_aplicados"]["operadora"] == "VIVO"
    assert res["metadados_fonte"]["filtros_aplicados"]["servico"] == "SCM"
    assert res["metadados_fonte"]["filtros_aplicados"]["uf"] == "SP"
    assert len(res["registros"]) > 0
    assert "media_nota_iqs" in res["estatisticas_agregadas"]
    assert "| ano_mes |" in res["tabela_markdown"]


async def test_consultar_indicadores_rede() -> None:
    res = await anatel_service.consultar_indicadores_rede(
        operadora="Unifique",
        servico="SCM",
        indicador="download",
        uf="SC",
    )
    assert len(res["registros"]) > 0
    assert all(r["indicador"] == "velocidade_download" for r in res["registros"])
    assert res["estatisticas_agregadas"]["taxa_cumprimento_metas_pct"] == 100.0


async def test_consultar_reclamacoes_ida() -> None:
    res = await anatel_service.consultar_reclamacoes_ida(
        operadora="Claro",
        servico="celular",
        uf="RJ",
    )
    assert len(res["registros"]) > 0
    assert res["registros"][0]["operadora"] == "CLARO"
    assert res["registros"][0]["servico"] == "SMP"
    assert res["estatisticas_agregadas"]["media_nota_ida"] > 0


async def test_consultar_pesquisa_satisfacao() -> None:
    res = await anatel_service.consultar_pesquisa_satisfacao(
        servico="banda larga",
        uf="CE",
        ano=2025,
    )
    assert len(res["registros"]) > 0
    assert res["estatisticas_agregadas"]["lider_satisfacao"]["operadora"] == "BRISANET"


async def test_comparar_operadoras_quatro_pilares() -> None:
    res = await anatel_service.comparar_operadoras(
        servico="fibra",
        uf="SC",
    )
    assert len(res["registros"]) >= 4
    first = res["registros"][0]
    assert first["posicao_ranking"] == 1
    assert "score_consolidado_0_10" in first
    assert "nota_iqs" in first
    assert "nota_ida" in first
    assert "nota_isg_satisfacao" in first


async def test_buscar_datasets_ckan_e_glossario() -> None:
    ckan_res = await anatel_service.buscar_datasets_ckan_anatel(termo_busca="rqual")
    assert len(ckan_res["registros"]) >= 1

    gloss_res = await anatel_service.consultar_glossario_metodologia_anatel(topico="rqual_iqs")
    assert len(gloss_res["registros"]) == 1
    assert gloss_res["registros"][0]["topico"] == "rqual_iqs"
