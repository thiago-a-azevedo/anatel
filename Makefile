PROJECT_ID ?= nprod-demo
REGION     ?= us-central1
PY         ?= .venv/bin/python
GCLOUD     ?= gcloud

.PHONY: install lint test eval adk-eval e2e playground run tf-bootstrap tf-init infra-plan infra verify-infra infra-destroy deploy adk-deploy deploy-test destroy

install:            ## Create venv and install deps
	uv venv .venv --python 3.12 && uv pip install --python $(PY) -e ".[dev]"

lint:               ## Static checks
	$(PY) -m ruff check anatel_advisor tests deployment

test:               ## Unit tests (offline)
	$(PY) -m pytest tests/unit -q

eval:               ## Golden-dataset evaluation (Gemini + live MCP)
	$(PY) -m pytest tests/eval -m eval -q

adk-eval:           ## Golden-dataset evaluation via ADK CLI
	.venv/bin/adk eval anatel_advisor tests/eval/data/anatel_golden.evalset.json --config_file_path tests/eval/data/test_config.json

e2e:                ## Run every user story against the deployed Agent Runtime (Agent Platform)
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) tests/e2e/run_remote_stories.py

playground:         ## ADK dev UI with persistent local sessions + memory
	.venv/bin/adk web --session_service_uri sqlite:///.adk/sessions.db .

run:                ## CLI chat
	.venv/bin/adk run anatel_advisor

TF       ?= terraform
TF_DIR   := terraform
TF_VARS  := -var-file=environments/$(PROJECT_ID).tfvars $(if $(wildcard $(TF_DIR)/environments/$(PROJECT_ID).private.tfvars),-var-file=environments/$(PROJECT_ID).private.tfvars)

tf-bootstrap:       ## Create the versioned remote-state bucket (once per project)
	PROJECT_ID=$(PROJECT_ID) REGION=$(REGION) GCLOUD=$(GCLOUD) bash $(TF_DIR)/bootstrap/create_state_bucket.sh

tf-init:            ## terraform init with the environment backend
	cd $(TF_DIR) && $(TF) init -input=false -backend-config=environments/$(PROJECT_ID).backend.hcl

infra-plan:         ## Show infrastructure changes (no side effects)
	cd $(TF_DIR) && $(TF) plan -input=false $(TF_VARS)

infra:              ## Apply infrastructure (Terraform)
	cd $(TF_DIR) && $(TF) apply -input=false $(TF_VARS)

verify-infra:       ## Drift check: fails if real infra differs from code
	cd $(TF_DIR) && $(TF) plan -input=false -detailed-exitcode -lock=false $(TF_VARS)

infra-destroy:      ## Destroy ALL infrastructure managed by Terraform
	cd $(TF_DIR) && $(TF) destroy -input=false $(TF_VARS)

deploy:             ## Deploy/update on Agent Runtime (Gemini Enterprise Agent Platform)
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) deployment/deploy.py

adk-deploy:         ## Deploy via ADK CLI (`adk deploy agent_engine`)
	.venv/bin/adk deploy agent_engine --project=$(PROJECT_ID) --region=$(REGION) --staging_bucket=gs://$(PROJECT_ID)-anatel-advisor-staging --display_name=anatel-telecom-advisor anatel_advisor

deploy-test:        ## Smoke-test the deployed agent
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) deployment/deploy.py --test "Compare as operadoras de banda larga no CE"

destroy:            ## Delete the Agent Runtime instance, then all infrastructure
	GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) $(PY) deployment/deploy.py --delete
	$(MAKE) infra-destroy PROJECT_ID=$(PROJECT_ID)
