PROJECT_ID ?= nprod-demo
REGION     ?= us-central1
PY         ?= .venv/bin/python
GCLOUD     ?= gcloud
GITHUB_REPO ?= thiago-a-azevedo/anatel

.PHONY: install lint test eval e2e playground run infra cicd deploy deploy-test destroy

install:            ## Create venv and install deps
	uv venv .venv --python 3.12 && uv pip install --python $(PY) -e ".[dev]"

lint:               ## Static checks
	$(PY) -m ruff check anatel_advisor tests deployment

test:               ## Unit tests (offline)
	$(PY) -m pytest tests/unit -q

eval:               ## Golden-dataset evaluation (Gemini + live MCP)
	$(PY) -m pytest tests/eval -m eval -q

e2e:                ## Run every user story against the deployed Agent Engine
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) tests/e2e/run_remote_stories.py

playground:         ## ADK dev UI with persistent local sessions + memory
	.venv/bin/adk web --session_service_uri sqlite:///.adk/sessions.db .

run:                ## CLI chat
	.venv/bin/adk run anatel_advisor

infra:              ## Provision GCP resources with gcloud (idempotent)
	PROJECT_ID=$(PROJECT_ID) REGION=$(REGION) GCLOUD=$(GCLOUD) bash infra/setup.sh

cicd:               ## Provision Workload Identity Federation + deployer SA for CI/CD
	PROJECT_ID=$(PROJECT_ID) GCLOUD=$(GCLOUD) GITHUB_REPO=$(GITHUB_REPO) bash infra/setup_cicd.sh

deploy:             ## Deploy/update on Vertex AI Agent Engine (idempotent)
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) deployment/deploy.py

deploy-test:        ## Smoke-test the deployed agent
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) deployment/deploy.py --test "Compare Brisanet, Claro e Vivo em banda larga no CE"

destroy:            ## Delete Agent Engine + infra
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) deployment/deploy.py --delete; PROJECT_ID=$(PROJECT_ID) bash infra/teardown.sh
