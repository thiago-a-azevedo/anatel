"""Response entities shared by every Anatel tool (field names are the API contract).

Field names stay in Portuguese on purpose: they are the wire contract consumed by the
ADK agent (``anatel_advisor/schemas.py``: ``registros``, ``metadados_fonte``,
``origem_leitura`` ...) and by Gemini Enterprise actions.
"""

from typing import Any

from pydantic import BaseModel, Field


class FonteMetadados(BaseModel):
    """Provenance metadata for the Anatel data source behind a response."""

    pilar: str = Field(description="Anatel data pillar that was queried")
    url_oficial_anatel: str = Field(description="Official dataset URL on Anatel's open-data portal")
    origem_leitura: str = Field(
        description="Effective data origin: 'cache_ram_http', 'http_direto_anatel' or 'fallback_seed_ram'"
    )
    filtros_aplicados: dict[str, Any] = Field(default_factory=dict)
    total_registros_encontrados: int = Field(description="Total rows matched before pagination")
    registros_retornados: int = Field(description="Rows returned in this response")


class RespostaPadraoAnatel(BaseModel):
    """Standard JSON output of every MCP tool / Gemini Enterprise action."""

    resumo_executivo: str = Field(
        description="Direct analytical summary answering the query with the main highlights"
    )
    estatisticas_agregadas: dict[str, Any] = Field(
        description="Consolidated metrics (averages, best/worst operators, target compliance)"
    )
    registros: list[dict[str, Any]] = Field(
        description="Main filtered and sorted rows (limited to 25-50 rows)"
    )
    tabela_markdown: str = Field(
        description="Markdown table ready to be shown to the user"
    )
    metadados_fonte: FonteMetadados = Field(
        description="Official Anatel source, in-memory cache state and applied filters"
    )
