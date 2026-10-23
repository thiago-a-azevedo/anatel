"""Deploys (or updates) the Anatel Telecom Advisor on Agent Runtime on Gemini Enterprise Agent Platform.

Idempotent and CI-safe:

* The target instance is discovered by ``display_name`` (no local state file), so
  every CI run updates the same Agent Runtime instance instead of creating a new one.
* Non-secret environment configuration (resource names written by
  Terraform (``terraform/``)) is versioned in ``deployment/environments/<project>.env``.
  Secrets never live there: the MCP endpoint stays in Secret Manager.

Usage:
    python deployment/deploy.py                       # create or update
    python deployment/deploy.py --test "Quais as principais reclamações por operadora no celular em SP?"
    python deployment/deploy.py --print-name          # resolved runtime resource name
    python deployment/deploy.py --delete
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DISPLAY_NAME = os.getenv("AGENT_DISPLAY_NAME", "anatel-telecom-advisor")
REQUIREMENTS_FILE = "requirements.txt"
ENTRYPOINT_MODULE = "anatel_advisor.agent_engine_app"
ENTRYPOINT_OBJECT = "agent_engine"


def load_environment() -> None:
    """Loads ``deployment/environments/<project>.env`` (or ``DEPLOY_ENV_FILE``).

    Values already present in the process environment win, so CI can override.
    """
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
    candidates = [os.getenv("DEPLOY_ENV_FILE")]
    if project:
        candidates.append(str(ROOT / "deployment" / "environments" / f"{project}.env"))
    envs = sorted((ROOT / "deployment" / "environments").glob("*.env"))
    if not project and len(envs) == 1:
        candidates.append(str(envs[0]))
    for candidate in filter(None, candidates):
        path = Path(candidate)
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip() and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
            return
    sys.exit(
        "No environment file found. Run `make infra PROJECT_ID=<project>` or set DEPLOY_ENV_FILE."
    )


def get_client():
    import vertexai

    return vertexai.Client(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


def find_engine(client) -> str | None:
    """Returns the resource name of the Agent Runtime instance with ``DISPLAY_NAME``, if any."""
    matches = [
        e.api_resource.name
        for e in client.agent_engines.list(config={"filter": f'display_name="{DISPLAY_NAME}"'})
    ]
    if len(matches) > 1:
        sys.exit(f"Ambiguous: {len(matches)} Agent Runtime instances named '{DISPLAY_NAME}': {matches}")
    return matches[0] if matches else None


def _runtime_env() -> dict[str, str]:
    """Non-secret runtime configuration. Secrets stay in Secret Manager."""
    keys = ["REPORTS_BUCKET", "MCP_URL_SECRET_ID", "MODEL_ARMOR_TEMPLATE", "VERTEX_SEARCH_DATASTORE"]
    env = {k: os.environ[k] for k in keys if os.getenv(k)}
    env.update(
        {
            "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
            "PII_REDACTION_MODE": "dlp",
            "LOG_LEVEL": "INFO",
            # Observability (docs: agent-engine/manage/tracing). The Console's Traces /
            # Dashboards tabs read these from deploymentSpec.env, so API deployments
            # must set them explicitly:
            #  - ENABLE_TELEMETRY: OpenTelemetry traces + logs + metrics -> Cloud Trace /
            #    Cloud Logging / Cloud Monitoring (modern toggle, visible in the Console).
            #  - OTEL_SEMCONV_STABILITY_OPT_IN: latest GenAI semantic conventions
            #    (gen_ai.* spans, inference events and token/latency metrics).
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
            # Privacy: never copy prompts, responses, tool arguments or user ids into
            # span attributes / GenAI events (docs suggest EVENT_ONLY to include them).
            # Intent and outcome are logged (PII-redacted) by the ObservabilityPlugin.
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "NO_CONTENT",
            "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
        }
    )
    return env


def _smoke_test(client, name: str, query: str) -> None:
    remote = client.agent_engines.get(name=name)

    async def _run():
        session = await remote.async_create_session(user_id="cli-tester")
        async for event in remote.async_stream_query(
            user_id="cli-tester", session_id=session["id"], message=query
        ):
            for part in (event.get("content") or {}).get("parts", []):
                if part.get("text"):
                    print(f"[{event.get('author')}] {part['text']}")

    asyncio.run(_run())


def deploy(client, existing: str | None) -> str:
    # Source-based deployment: Agent Runtime imports the entrypoint from the uploaded
    # package instead of unpickling a local object. The class-method schema is
    # generated locally from the same AdkApp the runtime will build.
    from google.protobuf import json_format
    from vertexai._genai import _agent_engines_utils as ae_utils

    from anatel_advisor.agent_engine_app import agent_engine

    class_methods = [
        json_format.MessageToDict(spec)
        for spec in ae_utils._generate_class_methods_spec_or_raise(
            agent=agent_engine,
            operations=ae_utils._get_registered_operations(agent=agent_engine),
        )
    ]
    os.chdir(ROOT)  # source_packages / requirements_file are relative paths
    config = {
        "display_name": DISPLAY_NAME,
        "description": "Multi-agent analyst over official Anatel telecom quality data (MCP).",
        "source_packages": ["anatel_advisor", REQUIREMENTS_FILE],
        "entrypoint_module": ENTRYPOINT_MODULE,
        "entrypoint_object": ENTRYPOINT_OBJECT,
        "requirements_file": REQUIREMENTS_FILE,
        "class_methods": class_methods,
        "agent_framework": "google-adk",
        "service_account": os.environ["AGENT_SERVICE_ACCOUNT"],
        "env_vars": _runtime_env(),
        "min_instances": int(os.getenv("AGENT_MIN_INSTANCES", "1")),
        "max_instances": int(os.getenv("AGENT_MAX_INSTANCES", "5")),
        "labels": {"app": "anatel-advisor", "managed-by": "deploy-py"},
    }
    if existing:
        print(f"Updating {existing} ...")
        remote = client.agent_engines.update(name=existing, config=config)
    else:
        print("Creating Agent Runtime instance (this takes a few minutes) ...")
        remote = client.agent_engines.create(config=config)
    return remote.api_resource.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--print-name", action="store_true")
    parser.add_argument("--test", metavar="QUERY")
    args = parser.parse_args()

    load_environment()
    client = get_client()
    existing = find_engine(client)

    if args.print_name:
        print(existing or "")
        return
    if args.delete:
        if existing:
            client.agent_engines.delete(name=existing, force=True)
            print(f"Deleted {existing}")
        return
    if args.test:
        if not existing:
            sys.exit("No deployment found. Run without --test first.")
        _smoke_test(client, existing, args.test)
        return

    name = deploy(client, existing)
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    print(f"Deployed: {name}")
    print(
        "Console: https://console.cloud.google.com/vertex-ai/agents/agent-engines/"
        f"locations/{location}/agent-engines/{name.split('/')[-1]}"
        f"?project={os.environ['GOOGLE_CLOUD_PROJECT']}"
    )


if __name__ == "__main__":
    main()
