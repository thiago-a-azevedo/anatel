"""Deploys (or updates) the Anatel Telecom Advisor on Vertex AI Agent Engine (Runtime).

Reads infrastructure outputs from ``.env.deploy`` (written by ``infra/setup.sh``).

Usage:
    python deployment/deploy.py                # create or update
    python deployment/deploy.py --test "Compare Vivo e Claro no SMP em SP"
    python deployment/deploy.py --delete
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE_FILE = ROOT / "deployment" / ".agent_engine.json"
DISPLAY_NAME = "anatel-telecom-advisor"

REQUIREMENTS_FILE = "requirements.txt"
ENTRYPOINT_MODULE = "anatel_advisor.agent_engine_app"
ENTRYPOINT_OBJECT = "agent_engine"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        sys.exit(f"{path} not found. Run infra/setup.sh first.")
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _runtime_env() -> dict[str, str]:
    """Non-secret runtime configuration. Secrets stay in Secret Manager."""
    keys = [
        "REPORTS_BUCKET",
        "MCP_URL_SECRET_ID",
        "MODEL_ARMOR_TEMPLATE",
        "VERTEX_SEARCH_DATASTORE",
    ]
    env = {k: os.environ[k] for k in keys if os.getenv(k)}
    env.update(
        {
            "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
            "PII_REDACTION_MODE": "dlp",
            "LOG_LEVEL": "INFO",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
        }
    )
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--test", metavar="QUERY")
    args = parser.parse_args()

    _load_env_file(ROOT / ".env.deploy")
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    import vertexai

    client = vertexai.Client(project=project, location=location)
    existing = json.loads(STATE_FILE.read_text())["name"] if STATE_FILE.exists() else None

    if args.delete:
        if existing:
            client.agent_engines.delete(name=existing, force=True)
            STATE_FILE.unlink()
            print(f"Deleted {existing}")
        return

    if args.test:
        if not existing:
            sys.exit("No deployment found. Run without --test first.")
        remote = client.agent_engines.get(name=existing)
        import asyncio

        async def _run():
            session = await remote.async_create_session(user_id="cli-tester")
            async for event in remote.async_stream_query(
                user_id="cli-tester", session_id=session["id"], message=args.test
            ):
                for part in (event.get("content") or {}).get("parts", []):
                    if part.get("text"):
                        print(f"[{event.get('author')}] {part['text']}")

        asyncio.run(_run())
        return

    # Source-based deployment: Agent Engine imports the entrypoint from the uploaded
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
        "min_instances": 1,
        "max_instances": 5,
        "labels": {"app": "anatel-advisor", "course": "ai-in-5-days"},
    }

    if existing:
        print(f"Updating {existing} ...")
        remote = client.agent_engines.update(name=existing, config=config)
    else:
        print("Creating Agent Engine instance (this takes a few minutes) ...")
        remote = client.agent_engines.create(config=config)

    name = remote.api_resource.name
    STATE_FILE.write_text(json.dumps({"name": name}, indent=2))
    print(f"Deployed: {name}")
    print(
        "Console: https://console.cloud.google.com/vertex-ai/agents/agent-engines/"
        f"locations/{location}/agent-engines/{name.split('/')[-1]}?project={project}"
    )


if __name__ == "__main__":
    main()
