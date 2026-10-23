from typing import Any

from pydantic import BaseModel, Field


class FonteMetadados(BaseModel):
    """Metadados de rastreabilidade da fonte de dados da Anatel."""

    pilar: str = Field(description="Pilar de dados da Anatel consultado")
    url_oficial_anatel: str = Field(description="URL oficial do conjunto de dados no portal da Anatel")
    origem_leitura: str = Field(
        description="Origem efetiva da leitura: 'cache_ram_http', 'http_direto_anatel' ou 'fallback_seed_ram'"
    )
    filtros_aplicados: dict[str, Any] = Field(default_factory=dict)
    total_registros_encontrados: int = Field(description="Total de registros antes do truncamento de página")
    registros_retornados: int = Field(description="Quantidade de registros retornados nesta resposta")


class RespostaPadraoAnatel(BaseModel):
    """Estrutura padronizada de saída JSON para as Actions do Gemini Enterprise e Tools MCP."""

    resumo_executivo: str = Field(
        description="Síntese analítica direta respondendo à consulta com os principais destaques"
    )
    estatisticas_agregadas: dict[str, Any] = Field(
        description="Métricas consolidadas (médias, melhores/piores operadoras, cumprimento de metas)"
    )
    registros: list[dict[str, Any]] = Field(
        description="Lista dos principais registros filtrados e ordenados (limitada a 25-50 linhas)"
    )
    tabela_markdown: str = Field(
        description="Tabela formatada em Markdown pronta para apresentação ao usuário"
    )
    metadados_fonte: FonteMetadados = Field(
        description="Informações sobre a fonte oficial da Anatel, cache em memória e filtros"
    )
