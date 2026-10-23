#!/usr/bin/env bash
# Tears down resources created by infra/setup.sh (keeps the shared MCP service).
set -euo pipefail
PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
GCLOUD="${GCLOUD:-gcloud}"
SA_EMAIL="anatel-advisor-sa@${PROJECT_ID}.iam.gserviceaccount.com"
g() { "${GCLOUD}" --project="${PROJECT_ID}" --quiet "$@"; }

read -r -p "Delete Anatel Advisor resources in ${PROJECT_ID}? [y/N] " ok
[[ "${ok}" == "y" ]] || exit 1

g model-armor templates delete anatel-advisor-guardrails --location="${REGION}" || true
g secrets delete anatel-mcp-url || true
g storage rm -r "gs://${PROJECT_ID}-anatel-advisor-reports" || true
g storage rm -r "gs://${PROJECT_ID}-anatel-advisor-staging" || true
g run services remove-iam-policy-binding mcp-anatel --region="${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/run.invoker || true
g iam service-accounts delete "${SA_EMAIL}" || true
echo "Agent Engine instances must be deleted from the console or with deployment/deploy.py --delete."
