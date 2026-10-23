import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from src.application.anatel_service import anatel_service
from src.domain.glossary import get_glossary_content
from src.infrastructure.fallback_seed import FALLBACK_CKAN_PACKAGES

# Instância oficial MCPServer (mcp 2.x) compatível com StreamableHTTP (/mcp)
# para o Gemini Enterprise App (Custom MCP Server) e clientes stdio locais
mcp = MCPServer(
    name="mcp-anatel",
    instructions=(
        "Servidor MCP especialista em dados abertos da Anatel sobre Consumidor e Qualidade: "
        "RQUAL (Selo de Qualidade A-E e IQS), Indicadores Operacionais de Qualidade de Rede "
        "(download, upload, latência, jitter, perda de pacotes, disponibilidade), "
        "Reclamações (Anatel Consumidor / IDA) e Pesquisa de Satisfação e Qualidade Percebida (ISG)."
    ),
)


@mcp.tool(
    name="consultar_rqual_iqs",
    description=(
        "Consulta o Selo de Qualidade RQUAL (A, B, C, D ou E) e a nota do IQS "
        "(Índice de Qualidade do Serviço, de 0 a 10) das operadoras de telecomunicações na Anatel. "
        "Permite filtrar por operadora (ex: Vivo, Claro, TIM, Oi, Brisanet, Unifique, Algar), "
        "serviço (SMP/celular, SCM/banda larga/fibra, STFC/fixo), UF (ex: SP, RJ, BR) e município."
    ),
)
async def consultar_rqual_iqs(
    operadora: str | None = None,
    servico: str | None = None,
    uf: str | None = None,
    municipio: str | None = None,
    ano_mes: str | None = None,
    limite: int = 25,
) -> dict[str, Any]:
    return await anatel_service.consultar_rqual_iqs(
        operadora=operadora,
        servico=servico,
        uf=uf,
        municipio=municipio,
        ano_mes=ano_mes,
        limite=limite,
    )


@mcp.tool(
    name="consultar_indicadores_rede",
    description=(
        "Consulta os indicadores operacionais de qualidade de rede aferidos no RQUAL da Anatel: "
        "velocidade_download (% cumprimento), velocidade_upload (% cumprimento), latencia (ms), "
        "jitter (ms), perda_pacotes (%) e disponibilidade (% uptime da rede), comparando com a meta regulatória."
    ),
)
async def consultar_indicadores_rede(
    operadora: str | None = None,
    servico: str | None = None,
    indicador: str | None = None,
    uf: str | None = None,
    municipio: str | None = None,
    ano_mes: str | None = None,
    limite: int = 25,
) -> dict[str, Any]:
    return await anatel_service.consultar_indicadores_rede(
        operadora=operadora,
        servico=servico,
        indicador=indicador,
        uf=uf,
        municipio=municipio,
        ano_mes=ano_mes,
        limite=limite,
    )


@mcp.tool(
    name="consultar_reclamacoes_ida",
    description=(
        "Consulta dados de reclamações de clientes (Anatel Consumidor) e o ranking do IDA "
        "(Índice de Desempenho no Atendimento, de 0 a 100): volume total de reclamações, "
        "índice de reclamações por 1.000 acessos, principal motivo de reclamação, "
        "taxa de resolução (%) e prazo médio de resposta em dias."
    ),
)
async def consultar_reclamacoes_ida(
    operadora: str | None = None,
    servico: str | None = None,
    uf: str | None = None,
    motivo: str | None = None,
    ano_mes: str | None = None,
    limite: int = 25,
) -> dict[str, Any]:
    return await anatel_service.consultar_reclamacoes_ida(
        operadora=operadora,
        servico=servico,
        uf=uf,
        motivo=motivo,
        ano_mes=ano_mes,
        limite=limite,
    )


@mcp.tool(
    name="consultar_pesquisa_satisfacao",
    description=(
        "Consulta os resultados da Pesquisa de Satisfação e Qualidade Percebida da Anatel: "
        "nota do ISG (Índice de Satisfação Geral, 0 a 10) e notas específicas de Funcionamento, "
        "Atendimento (telefônico/digital) e Cobrança/Recarga por operadora, serviço e UF."
    ),
)
async def consultar_pesquisa_satisfacao(
    operadora: str | None = None,
    servico: str | None = None,
    uf: str | None = None,
    ano: int | None = None,
    limite: int = 25,
) -> dict[str, Any]:
    return await anatel_service.consultar_pesquisa_satisfacao(
        operadora=operadora,
        servico=servico,
        uf=uf,
        ano=ano,
        limite=limite,
    )


@mcp.tool(
    name="comparar_operadoras",
    description=(
        "Compara operadoras lado a lado em uma UF/município e serviço (ex: SCM/banda larga ou SMP/móvel), "
        "cruzando automaticamente os 4 pilares da Anatel (Selo RQUAL/IQS + Indicadores de Rede + "
        "Reclamações/IDA + Pesquisa de Satisfação ISG) e gerando um ranking ponderado de 0 a 10."
    ),
)
async def comparar_operadoras(
    servico: str = "SCM",
    uf: str = "BR",
    municipio: str | None = None,
    operadoras: list[str] | None = None,
) -> dict[str, Any]:
    return await anatel_service.comparar_operadoras(
        servico=servico,
        uf=uf,
        municipio=municipio,
        operadoras=operadoras,
    )


@mcp.tool(
    name="buscar_datasets_ckan_anatel",
    description=(
        "Busca conjuntos de dados abertos, metadados e URLs oficiais de arquivos CSV/ZIP "
        "diretamente no catálogo CKAN / Portal de Dados Abertos da Anatel."
    ),
)
async def buscar_datasets_ckan_anatel(
    termo_busca: str = "qualidade rqual consumidor",
    limite: int = 10,
) -> dict[str, Any]:
    return await anatel_service.buscar_datasets_ckan_anatel(
        termo_busca=termo_busca,
        limite=limite,
    )


@mcp.tool(
    name="consultar_glossario_metodologia_anatel",
    description=(
        "Action dedicada para consultar o glossário regulatório e a metodologia oficial da Anatel: "
        "significado de RQUAL, IQS, Selos A-E, IDA, ISG, siglas de serviços (SMP, SCM, STFC, SeAC), "
        "metas de qualidade de rede e mapeamento de grupos econômicos. "
        "Tópicos aceitos: 'geral', 'rqual_iqs', 'indicadores_rede', 'reclamacoes_ida', 'pesquisa_satisfacao', 'servicos_operadoras'."
    ),
)
async def consultar_glossario_metodologia_anatel(
    topico: str | None = "geral",
) -> dict[str, Any]:
    return await anatel_service.consultar_glossario_metodologia_anatel(topico=topico)


# ============================================================================
# MCP Resources (para clientes MCP Desktop como Antigravity, Claude, Cursor)
# ============================================================================

@mcp.resource(
    "anatel://glossario/rqual-consumidor",
    name="Glossário Regulatório Anatel (RQUAL, IQS, IDA e Satisfação)",
    description="Dicionário completo de indicadores, selos A-E, metas técnicas de rede e siglas regulatórias da Anatel.",
    mime_type="application/json",
)
def resource_glossario_anatel() -> str:
    return json.dumps(get_glossary_content("geral"), ensure_ascii=False, indent=2)


@mcp.resource(
    "anatel://catalogo/datasets",
    name="Catálogo de Conjuntos de Dados Abertos da Anatel (Consumidor e Qualidade)",
    description="Lista de URLs oficiais dos painéis de dados abertos da Anatel para RQUAL, Reclamações e Satisfação.",
    mime_type="application/json",
)
def resource_catalogo_datasets() -> str:
    return json.dumps(FALLBACK_CKAN_PACKAGES, ensure_ascii=False, indent=2)


# ============================================================================
# MCP Prompts (Templates de Análise Prontos)
# ============================================================================

@mcp.prompt(
    name="analisar_qualidade_operadora",
    description="Gera um diagnóstico executivo completo sobre uma operadora em uma UF combinando RQUAL/IQS, Rede, Reclamações e Satisfação.",
)
def prompt_analisar_qualidade_operadora(operadora: str, uf: str = "BR", servico: str = "SCM") -> str:
    return (
        f"Elabore um diagnóstico executivo completo da operadora '{operadora}' no serviço '{servico}' na UF '{uf}' "
        "utilizando as tools do MCP Anatel na seguinte ordem:\n"
        "1. Chame `consultar_rqual_iqs` para obter o Selo RQUAL (A-E) e evolução da nota IQS.\n"
        "2. Chame `consultar_indicadores_rede` para verificar cumprimento de velocidade de download/upload, latência, jitter e disponibilidade.\n"
        "3. Chame `consultar_reclamacoes_ida` para avaliar o índice de reclamações por 1.000 acessos, principais motivos e nota IDA.\n"
        "4. Chame `consultar_pesquisa_satisfacao` para avaliar o ISG e a percepção do consumidor.\n"
        "Apresente uma tabela síntese e recomendações práticas."
    )


@mcp.prompt(
    name="comparativo_regional_telecom",
    description="Compara todas as operadoras de banda larga (SCM) ou móvel (SMP) em um estado/município para recomendar a melhor opção.",
)
def prompt_comparativo_regional(uf: str = "SP", servico: str = "SCM", municipio: str = "") -> str:
    mun_clause = f" no município de '{municipio}'" if municipio else ""
    return (
        f"Compare as operadoras de '{servico}' na UF '{uf}'{mun_clause} utilizando a tool `comparar_operadoras` "
        "e detalhe os pontos fortes e fracos de cada prestadora nos 4 pilares da Anatel (IQS, Rede, Reclamações/IDA e Satisfação)."
    )
