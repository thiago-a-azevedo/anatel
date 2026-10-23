PROJECT_ID ?= nprod-demo
REGION     ?= us-central1
PY         ?= .venv/bin/python
GCLOUD     ?= gcloud

.PHONY: install lint test eval playground run infra deploy deploy-test destroy

install:            ## Create venv and install deps
	uv venv .venv --python 3.12 && uv pip install --python $(PY) -e ".[dev]"

lint:               ## Static checks
	$(PY) -m ruff check anatel_advisor tests deployment

test:               ## Unit tests (offline)
	$(PY) -m pytest tests/unit -q

eval:               ## Golden-dataset evaluation (Gemini + live MCP)
	$(PY) -m pytest tests/eval -m eval -q

playground:         ## ADK dev UI with persistent local sessions + memory
	.venv/bin/adk web --session_service_uri sqlite:///.adk/sessions.db .

run:                ## CLI chat
	.venv/bin/adk run anatel_advisor

infra:              ## Provision GCP resources with gcloud (idempotent)
	PROJECT_ID=$(PROJECT_ID) REGION=$(REGION) GCLOUD=$(GCLOUD) bash infra/setup.sh

deploy:             ## Deploy/update on Vertex AI Agent Engine
	$(PY) deployment/deploy.py

deploy-test:        ## Smoke-test the deployed agent
	$(PY) deployment/deploy.py --test "Compare Brisanet, Claro e Vivo em banda larga no CE"

destroy:            ## Delete Agent Engine + infra
	$(PY) deployment/deploy.py --delete; PROJECT_ID=$(PROJECT_ID) bash infra/teardown.sh
