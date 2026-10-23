"""Local function tools used by the analysis and reporting agents.

Every tool:

* has a specific, action-oriented name (``calculate_weighted_operator_ranking``,
  ``export_report_to_gcs``) instead of generic verbs;
* documents its purpose and every argument (ADK forwards the docstring to Gemini);
* uses typed Pydantic models for inputs/outputs (explicit JSON schema);
* never raises to the LLM: failures return ``status="error"`` plus a
  ``recovery_hint`` that tells the model how to fix the call.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from pydantic import ValidationError

from ..config import get_settings
from ..pii import redact
from ..schemas import (
    BRAZILIAN_UFS,
    GLOSSARY_TOPICS,
    KNOWN_OPERATORS,
    NETWORK_INDICATORS,
    SERVICE_ALIASES,
    ExportReportResult,
    OperatorScores,
    RankedOperator,
    RankingResult,
    RankingWeights,
)

logger = logging.getLogger(__name__)

_MAX_REPORT_CHARS = 200_000


def list_supported_anatel_filters() -> dict:
    """Lists the filter values accepted by the Anatel data tools.

    Call this BEFORE querying data whenever the user mentions a state, service or
    operator in free text and you are unsure of the exact code to send.

    Returns:
      A dict with the valid ``ufs`` (state codes + 'BR'), ``servicos`` (alias ->
      Anatel service code), ``operadoras`` (known operator names), ``indicadores_rede``
      (network indicator ids) and ``topicos_glossario`` (glossary topics).
    """
    return {
        "status": "success",
        "ufs": sorted(BRAZILIAN_UFS),
        "servicos": SERVICE_ALIASES,
        "operadoras": list(KNOWN_OPERATORS),
        "indicadores_rede": list(NETWORK_INDICATORS),
        "topicos_glossario": list(GLOSSARY_TOPICS),
        "formato_ano_mes": "YYYY-MM (ex.: 2026-09)",
    }


def calculate_weighted_operator_ranking(
    operators: list[OperatorScores],
    weights: RankingWeights | None = None,
) -> dict:
    """Ranks telecom operators with user-defined weights over the 3 Anatel score pillars.

    Use this when the user wants a ranking that prioritizes a specific pillar (e.g.
    "I care mostly about customer service" -> raise ``ida``). The default weights
    replicate Anatel's consolidated score (IQS 35%, IDA 30%, ISG 35%). IDA (0-100) is
    rescaled to 0-10 before weighting. Pillars missing for an operator are skipped and
    the remaining weights are renormalized for that operator.

    Args:
      operators: Per-operator scores copied verbatim from Anatel tool outputs
        (``nota_iqs`` 0-10, ``nota_ida`` 0-100, ``nota_isg`` 0-10).
      weights: Relative weights for ``iqs``, ``ida`` and ``isg``. Any non-negative
        numbers; they are normalized to sum to 1.

    Returns:
      A ``RankingResult`` dict with the ordered ``ranking`` and ``weights_normalized``,
      or ``status='error'`` with a ``recovery_hint``.
    """
    try:
        ops = [o if isinstance(o, OperatorScores) else OperatorScores.model_validate(o) for o in operators]
        w = weights if isinstance(weights, RankingWeights) else RankingWeights.model_validate(weights or {})
    except ValidationError as exc:
        return RankingResult(
            status="error",
            error_message=f"Invalid input: {exc.errors()[0]['msg']}",
            recovery_hint=(
                "Send scores exactly as returned by the Anatel tools: nota_iqs and nota_isg "
                "between 0 and 10, nota_ida between 0 and 100."
            ),
        ).model_dump()

    if not ops:
        return RankingResult(
            status="error",
            error_message="No operators provided.",
            recovery_hint="Call comparar_operadoras or consultar_rqual_iqs first and pass its records.",
        ).model_dump()

    total = w.iqs + w.ida + w.isg
    if total <= 0:
        return RankingResult(
            status="error",
            error_message="All weights are zero.",
            recovery_hint="Use at least one positive weight, e.g. {'iqs': 1, 'ida': 1, 'isg': 1}.",
        ).model_dump()
    norm = {"iqs": w.iqs / total, "ida": w.ida / total, "isg": w.isg / total}

    scored: list[tuple[str, float, list[str]]] = []
    for op in ops:
        pillars = {
            "iqs": op.nota_iqs,
            "ida": op.nota_ida / 10 if op.nota_ida is not None else None,
            "isg": op.nota_isg,
        }
        available = {k: v for k, v in pillars.items() if v is not None and norm[k] > 0}
        if not available:
            continue
        weight_sum = sum(norm[k] for k in available)
        score = sum(v * norm[k] for k, v in available.items()) / weight_sum
        scored.append((op.operadora.upper(), round(score, 2), sorted(available)))

    if not scored:
        return RankingResult(
            status="error",
            error_message="No operator has any score for the selected weights.",
            recovery_hint="Fetch at least one of nota_iqs, nota_ida or nota_isg per operator.",
        ).model_dump()

    scored.sort(key=lambda t: t[1], reverse=True)
    ranking = [
        RankedOperator(position=i + 1, operadora=n, weighted_score_0_10=s, pillars_used=p)
        for i, (n, s, p) in enumerate(scored)
    ]
    return RankingResult(
        status="success", ranking=ranking, weights_normalized={k: round(v, 3) for k, v in norm.items()}
    ).model_dump()


def export_report_to_gcs(title: str, markdown_report: str, tool_context: ToolContext) -> dict:
    """Publishes the final, critic-approved Markdown report to Cloud Storage.

    HIGH-STAKES ACTION: this writes a permanent, shareable artifact. It is wrapped with
    ``require_confirmation=True`` so ADK pauses and asks the human to approve before
    the function body runs. Only call it after the critic approved the report AND the
    user explicitly asked to save/export/share it.

    Args:
      title: Short human-readable report title, e.g. "Banda larga em SP - out/2026".
      markdown_report: The complete report in Markdown, including sources and period.
      tool_context: Injected by ADK (session/user metadata). Not provided by the LLM.

    Returns:
      An ``ExportReportResult`` dict with the ``gcs_uri`` on success, or
      ``status='error'`` with a ``recovery_hint``.
    """
    settings = get_settings()
    if not settings.reports_bucket:
        return ExportReportResult(
            status="error",
            error_message="REPORTS_BUCKET is not configured.",
            recovery_hint="Tell the user export is unavailable in this environment and show the report inline instead.",
        ).model_dump()
    if not title.strip() or not markdown_report.strip():
        return ExportReportResult(
            status="error",
            error_message="Empty title or report.",
            recovery_hint="Pass the full approved report text in markdown_report and a non-empty title.",
        ).model_dump()
    if len(markdown_report) > _MAX_REPORT_CHARS:
        return ExportReportResult(
            status="error",
            error_message=f"Report too large ({len(markdown_report)} chars).",
            recovery_hint=f"Summarize the report below {_MAX_REPORT_CHARS} characters and retry.",
        ).model_dump()

    report_id = f"{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    # Object names are derived from caller-supplied ids: restrict to a safe charset.
    user_id = re.sub(r"[^A-Za-z0-9_-]", "_", getattr(tool_context, "user_id", None) or "anonymous")[:64]
    blob_name = f"reports/{user_id}/{report_id}.md"
    body = f"# {title}\n\n{markdown_report}\n"
    try:
        from google.cloud import storage

        blob = storage.Client(project=settings.project_id).bucket(settings.reports_bucket).blob(blob_name)
        blob.metadata = {"title": redact(title) or "", "report_id": report_id}
        blob.upload_from_string(redact(body) or "", content_type="text/markdown; charset=utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.error("report_export_failed", extra={"report_id": report_id, "error": str(exc)})
        return ExportReportResult(
            status="error",
            report_id=report_id,
            error_message=f"Upload failed: {exc}",
            recovery_hint="Do not retry automatically. Show the report inline and tell the user the export failed.",
        ).model_dump()

    uri = f"gs://{settings.reports_bucket}/{blob_name}"
    tool_context.state["last_report_uri"] = uri
    return ExportReportResult(status="success", gcs_uri=uri, report_id=report_id).model_dump()


# Tool objects (the HITL wrapper is what makes export safe).
list_supported_anatel_filters_tool = FunctionTool(list_supported_anatel_filters)
calculate_weighted_operator_ranking_tool = FunctionTool(calculate_weighted_operator_ranking)
export_report_to_gcs_tool = FunctionTool(export_report_to_gcs, require_confirmation=True)
