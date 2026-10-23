"""Regression evaluation of the agent against the golden dataset.

Runs the full multi-agent system (Gemini + live Anatel MCP) on every golden case and
checks:

* tool trajectory (did the right agent call the right MCP tool, in order?);
* LLM-as-judge semantic response match (``final_response_match_v2``).

Run with ``make eval`` (requires GCP credentials). Excluded from ``make test``.
Equivalent CLI: ``adk eval anatel_advisor tests/eval/data/anatel_golden.evalset.json
--config_file_path tests/eval/data/test_config.json``.
"""

from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

DATA = Path(__file__).parent / "data"


@pytest.mark.eval
async def test_golden_dataset():
    await AgentEvaluator.evaluate(
        agent_module="anatel_advisor",
        eval_dataset_file_path_or_dir=str(DATA / "anatel_golden.evalset.json"),
        num_runs=1,
    )
