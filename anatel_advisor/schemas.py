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
    operadora: str | None = None
    servico: str | None = None
    uf: str | None = None
    municipio: str | None = None
    ano_mes: str | None = None
    limite: int = Field(default=25, ge=1, le=200)


class NetworkIndicatorsArgs(RqualIqsArgs):
    indicador: Literal[NETWORK_INDICATORS] | None = None  # type: ignore[valid-type]


class ComplaintsIdaArgs(_McpArgs):
    operadora: str | None = None
    servico: str | None = None
    uf: str | None = None
    motivo: str | None = None
    ano_mes: str | None = None
    limite: int = Field(default=25, ge=1, le=200)


class SatisfactionSurveyArgs(_McpArgs):
    operadora: str | None = None
    servico: str | None = None
    uf: str | None = None
    ano: int | None = Field(default=None, ge=2015, le=2100)
    limite: int = Field(default=25, ge=1, le=200)


class CompareOperatorsArgs(_McpArgs):
    servico: str = "SCM"
    uf: str = "BR"
    municipio: str | None = None
    operadoras: list[str] | None = Field(default=None, max_length=10)


class CkanSearchArgs(_McpArgs):
    termo_busca: str = Field(default="qualidade rqual consumidor", min_length=2, max_length=200)
    limite: int = Field(default=10, ge=1, le=50)


class GlossaryArgs(_McpArgs):
    topico: Literal[GLOSSARY_TOPICS] | None = "geral"  # type: ignore[valid-type]


MCP_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "consultar_rqual_iqs": RqualIqsArgs,
    "consultar_indicadores_rede": NetworkIndicatorsArgs,
    "consultar_reclamacoes_ida": ComplaintsIdaArgs,
    "consultar_pesquisa_satisfacao": SatisfactionSurveyArgs,
    "comparar_operadoras": CompareOperatorsArgs,
    "buscar_datasets_ckan_anatel": CkanSearchArgs,
    "consultar_glossario_metodologia_anatel": GlossaryArgs,
}


# --------------------------------------------------------------------------------------
# Local tool schemas
# --------------------------------------------------------------------------------------


class OperatorScores(BaseModel):
    """Per-operator pillar scores used to compute a custom weighted ranking."""

    operadora: str = Field(description="Operator name, e.g. 'VIVO'.")
    nota_iqs: float | None = Field(default=None, ge=0, le=10, description="RQUAL IQS, 0-10.")
    nota_ida: float | None = Field(default=None, ge=0, le=100, description="IDA score, 0-100.")
    nota_isg: float | None = Field(default=None, ge=0, le=10, description="ISG score, 0-10.")


class RankingWeights(BaseModel):
    """Weights (any positive numbers; they are normalized to sum to 1)."""

    iqs: float = Field(default=0.35, ge=0)
    ida: float = Field(default=0.30, ge=0)
    isg: float = Field(default=0.35, ge=0)


class RankedOperator(BaseModel):
    position: int
    operadora: str
    weighted_score_0_10: float
    pillars_used: list[str]


class RankingResult(BaseModel):
    status: Literal["success", "error"]
    ranking: list[RankedOperator] = Field(default_factory=list)
    weights_normalized: dict[str, float] = Field(default_factory=dict)
    error_message: str | None = None
    recovery_hint: str | None = None


class ExportReportResult(BaseModel):
    status: Literal["success", "error", "rejected"]
    gcs_uri: str | None = None
    report_id: str | None = None
    error_message: str | None = None
    recovery_hint: str | None = None


# --------------------------------------------------------------------------------------
# Agent output schemas
# --------------------------------------------------------------------------------------


class CriticIssue(BaseModel):
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
