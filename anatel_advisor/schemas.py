"""Explicit Pydantic schemas that constrain tool inputs/outputs and agent outputs.

These models are the single source of truth for:

* validating arguments the LLM sends to the remote Anatel MCP tools *before* the
  network call (see :class:`anatel_advisor.plugins.tool_guard.ToolGuardPlugin`);
* typing the inputs/outputs of local function tools (ADK derives the JSON schema
  exposed to Gemini from these annotations);
* forcing structured output from the critic agent (``output_schema``).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------------------
# Domain vocabularies
# --------------------------------------------------------------------------------------

BRAZILIAN_UFS: frozenset[str] = frozenset(
    {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
        "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO", "BR",
    }
)  # fmt: skip

SERVICE_ALIASES: dict[str, str] = {
    "SMP": "SMP", "CELULAR": "SMP", "MOVEL": "SMP", "MÓVEL": "SMP", "MOBILE": "SMP",
    "SCM": "SCM", "BANDA LARGA": "SCM", "BANDA_LARGA": "SCM", "FIBRA": "SCM", "BROADBAND": "SCM",
    "STFC": "STFC", "FIXO": "STFC", "TELEFONE FIXO": "STFC", "LANDLINE": "STFC",
    "SEAC": "SEAC", "TV": "SEAC", "TV POR ASSINATURA": "SEAC",
}  # fmt: skip

KNOWN_OPERATORS: tuple[str, ...] = (
    "VIVO", "CLARO", "TIM", "OI", "BRISANET", "ALGAR", "UNIFIQUE", "VERO", "DESKTOP", "SKY",
)  # fmt: skip

GLOSSARY_TOPICS: tuple[str, ...] = (
    "geral", "rqual_iqs", "indicadores_rede", "reclamacoes_ida", "pesquisa_satisfacao",
    "servicos_operadoras",
)  # fmt: skip

NETWORK_INDICATORS: tuple[str, ...] = (
    "velocidade_download", "velocidade_upload", "latencia", "jitter", "perda_pacotes",
    "disponibilidade",
)  # fmt: skip

_ANO_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def normalize_service(value: str | None) -> str | None:
    """Maps free-text service names (e.g. 'banda larga') to Anatel codes (SCM)."""
    if value is None:
        return None
    key = value.strip().upper()
    if key not in SERVICE_ALIASES:
        raise ValueError(
            f"Unknown service '{value}'. Use one of SMP (mobile), SCM (broadband), "
            "STFC (landline) or SEAC (pay TV)."
        )
    return SERVICE_ALIASES[key]


def normalize_uf(value: str | None) -> str | None:
    """Validates a Brazilian state code (2 letters) or 'BR' for national scope."""
    if value is None:
        return None
    key = value.strip().upper()
    if key not in BRAZILIAN_UFS:
        raise ValueError(
            f"Invalid UF '{value}'. Use the 2-letter state code (e.g. SP, RJ, MG) or 'BR'."
        )
    return key


# --------------------------------------------------------------------------------------
# MCP tool argument schemas (client-side validation of remote tools)
# --------------------------------------------------------------------------------------


class _McpArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("uf", mode="before", check_fields=False)
    @classmethod
    def _uf(cls, v: str | None) -> str | None:
        return normalize_uf(v)

    @field_validator("servico", mode="before", check_fields=False)
    @classmethod
    def _servico(cls, v: str | None) -> str | None:
        return normalize_service(v)

    @field_validator("ano_mes", mode="before", check_fields=False)
    @classmethod
    def _ano_mes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _ANO_MES.match(v.strip()):
            raise ValueError(f"Invalid ano_mes '{v}'. Use the YYYY-MM format, e.g. 2026-09.")
        return v.strip()


class RqualIqsArgs(_McpArgs):
    """Input schema for ``consultar_rqual_iqs`` (RQUAL quality seal A-E and IQS score 0-10)."""

    operadora: str | None = Field(default=None, description="Operator name, e.g. 'Vivo' or 'Brisanet'.")
    servico: str | None = Field(default=None, description="Anatel service code: SMP, SCM, STFC or SEAC.")
    uf: str | None = Field(default=None, description="2-letter Brazilian state code or 'BR'.")
    municipio: str | None = Field(default=None, description="Municipality name (optional).")
    ano_mes: str | None = Field(default=None, description="Reference period in YYYY-MM format.")
    limite: int = Field(default=25, ge=1, le=200, description="Max records to return (1-200).")


class NetworkIndicatorsArgs(RqualIqsArgs):
    """Input schema for ``consultar_indicadores_rede`` (speed, latency, jitter, loss, availability)."""

    indicador: Literal[NETWORK_INDICATORS] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Network indicator id (velocidade_download, latencia, jitter, perda_pacotes, disponibilidade).",
    )


class ComplaintsIdaArgs(_McpArgs):
    """Input schema for ``consultar_reclamacoes_ida`` (Anatel Consumidor complaints and IDA 0-100)."""

    operadora: str | None = Field(default=None, description="Operator name, e.g. 'TIM'.")
    servico: str | None = Field(default=None, description="Anatel service code: SMP, SCM, STFC or SEAC.")
    uf: str | None = Field(default=None, description="2-letter Brazilian state code or 'BR'.")
    motivo: str | None = Field(default=None, description="Complaint reason filter (optional).")
    ano_mes: str | None = Field(default=None, description="Reference period in YYYY-MM format.")
    limite: int = Field(default=25, ge=1, le=200, description="Max records to return (1-200).")


class SatisfactionSurveyArgs(_McpArgs):
    """Input schema for ``consultar_pesquisa_satisfacao`` (annual ISG satisfaction survey 0-10)."""

    operadora: str | None = Field(default=None, description="Operator name.")
    servico: str | None = Field(default=None, description="Anatel service code: SMP, SCM, STFC or SEAC.")
    uf: str | None = Field(default=None, description="2-letter Brazilian state code or 'BR'.")
    ano: int | None = Field(default=None, ge=2015, le=2100, description="Survey year (2015-2100).")
    limite: int = Field(default=25, ge=1, le=200, description="Max records to return (1-200).")


class CompareOperatorsArgs(_McpArgs):
    """Input schema for ``comparar_operadoras`` (cross-pillar comparison and consolidated ranking)."""

    servico: str = Field(default="SCM", description="Anatel service code: SMP, SCM, STFC or SEAC.")
    uf: str = Field(default="BR", description="2-letter Brazilian state code or 'BR'.")
    municipio: str | None = Field(default=None, description="Municipality name (optional).")
    operadoras: list[str] | None = Field(
        default=None, max_length=10, description="Optional list of up to 10 operators to compare."
    )


class CkanSearchArgs(_McpArgs):
    """Input schema for ``buscar_datasets_ckan_anatel`` (Anatel open-data CKAN catalog search)."""

    termo_busca: str = Field(
        default="qualidade rqual consumidor",
        min_length=2,
        max_length=200,
        description="Search terms for the Anatel open-data portal.",
    )
    limite: int = Field(default=10, ge=1, le=50, description="Max datasets to return (1-50).")


class GlossaryArgs(_McpArgs):
    """Input schema for ``consultar_glossario_metodologia_anatel`` (regulatory glossary)."""

    topico: Literal[GLOSSARY_TOPICS] | None = Field(  # type: ignore[valid-type]
        default="geral", description="Glossary topic identifier."
    )


MCP_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "consultar_rqual_iqs": RqualIqsArgs,
    "consultar_indicadores_rede": NetworkIndicatorsArgs,
    "consultar_reclamacoes_ida": ComplaintsIdaArgs,
    "consultar_pesquisa_satisfacao": SatisfactionSurveyArgs,
    "comparar_operadoras": CompareOperatorsArgs,
    "buscar_datasets_ckan_anatel": CkanSearchArgs,
    "consultar_glossario_metodologia_anatel": GlossaryArgs,
}


class McpSourceMetadata(BaseModel):
    """Provenance metadata returned inside ``structuredContent.metadados_fonte``."""

    model_config = ConfigDict(extra="allow")

    pilar: str | None = Field(default=None, description="Anatel quality pillar identifier.")
    origem_leitura: str | None = Field(default=None, description="Data origin (live or seed fallback).")
    periodo_referencia: str | None = Field(default=None, description="Reference period (YYYY-MM or year).")


class McpStructuredContent(BaseModel):
    """Structured payload inside an Anatel MCP tool response."""

    model_config = ConfigDict(extra="allow")

    registros: list[dict] | None = Field(default=None, description="Returned data rows.")
    metadados_fonte: McpSourceMetadata | None = Field(default=None, description="Source provenance.")


class McpToolOutput(BaseModel):
    """Output schema for responses returned by the remote Anatel MCP server."""

    model_config = ConfigDict(extra="allow")

    isError: bool = Field(default=False, description="True when the MCP server reports a tool error.")
    structuredContent: McpStructuredContent | None = Field(
        default=None, description="Structured tool output payload."
    )
    recovery_hint: str | None = Field(
        default=None, description="Actionable instruction added when recovery is needed."
    )


# --------------------------------------------------------------------------------------
# Local tool schemas
# --------------------------------------------------------------------------------------


class SupportedFiltersResult(BaseModel):
    """Output schema for ``list_supported_anatel_filters``."""

    status: Literal["success"] = "success"
    ufs: list[str] = Field(description="Valid 2-letter Brazilian state codes plus 'BR'.")
    servicos: dict[str, str] = Field(description="Free-text alias -> canonical Anatel service code.")
    operadoras: list[str] = Field(description="Canonical operator names known to the dataset.")
    indicadores_rede: list[str] = Field(description="Valid network indicator identifiers.")
    topicos_glossario: list[str] = Field(description="Valid glossary topic identifiers.")
    formato_ano_mes: str = Field(description="Expected YYYY-MM period format.")


class OperatorScores(BaseModel):
    """Per-operator pillar scores used to compute a custom weighted ranking."""

    operadora: str = Field(description="Operator name, e.g. 'VIVO'.")
    nota_iqs: float | None = Field(default=None, ge=0, le=10, description="RQUAL IQS, 0-10.")
    nota_ida: float | None = Field(default=None, ge=0, le=100, description="IDA score, 0-100.")
    nota_isg: float | None = Field(default=None, ge=0, le=10, description="ISG score, 0-10.")


class RankingWeights(BaseModel):
    """Weights (any positive numbers; they are normalized to sum to 1)."""

    iqs: float = Field(default=0.35, ge=0, description="Weight for RQUAL/IQS (default 0.35).")
    ida: float = Field(default=0.30, ge=0, description="Weight for Anatel Consumidor/IDA (default 0.30).")
    isg: float = Field(default=0.35, ge=0, description="Weight for Satisfaction/ISG (default 0.35).")


class RankedOperator(BaseModel):
    """Single row in the computed operator ranking."""

    position: int = Field(ge=1, description="1-based rank position.")
    operadora: str = Field(description="Operator name in uppercase.")
    weighted_score_0_10: float = Field(ge=0, le=10, description="Normalized weighted score (0-10).")
    pillars_used: list[str] = Field(description="Pillars included in this operator's score.")


class RankingResult(BaseModel):
    """Output schema for ``calculate_weighted_operator_ranking``."""

    status: Literal["success", "error"]
    ranking: list[RankedOperator] = Field(default_factory=list)
    weights_normalized: dict[str, float] = Field(default_factory=dict)
    error_message: str | None = None
    recovery_hint: str | None = None


class ExportReportResult(BaseModel):
    """Output schema for ``export_report_to_gcs``."""

    status: Literal["success", "error", "rejected"]
    gcs_uri: str | None = None
    report_id: str | None = None
    error_message: str | None = None
    recovery_hint: str | None = None


# --------------------------------------------------------------------------------------
# Agent output schemas
# --------------------------------------------------------------------------------------


class CriticIssue(BaseModel):
    """Single grounding or policy issue flagged by ``quality_critic``."""

    claim: str = Field(description="The exact sentence or number from the draft being challenged.")
    problem: Literal[
        "number_not_in_tool_output",
        "missing_source_or_period",
        "wrong_interpretation",
        "unsupported_recommendation",
        "off_topic_or_unsafe",
    ]
    fix: str = Field(description="Concrete correction the writer must apply.")


class CriticVerdict(BaseModel):
    """Structured self-evaluation produced by the critic agent."""

    approved: bool = Field(description="True only if every number is grounded in tool output.")
    groundedness_score: int = Field(ge=1, le=5, description="1 = hallucinated, 5 = fully grounded.")
    issues: list[CriticIssue] = Field(default_factory=list)
    summary: str = Field(description="One-sentence justification of the verdict.")
