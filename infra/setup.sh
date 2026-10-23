#!/usr/bin/env bash
# =============================================================================
# Infrastructure as Code (gcloud) for the Anatel Telecom Advisor.
#
# Idempotent: safe to re-run. Every step checks for existence before creating.
# Provisions:
#   1. Required Google Cloud APIs
#   2. Dedicated least-privilege service account for Vertex AI Agent Engine
#   3. IAM bindings (Vertex AI, Secret Manager, DLP, Model Armor, Trace, Logging,
#      Discovery Engine, Cloud Run invoker on the Anatel MCP service)
#   4. Secret Manager secret holding the MCP server URL (no hardcoded endpoints)
#   5. GCS buckets: Agent Engine staging + HITL-approved reports
#   6. Model Armor template (prompt injection/jailbreak, RAI, malicious URLs, SDP)
#   7. Vertex AI Search data store + Anatel methodology knowledge base
#   8. Writes deployment/environments/<project>.env consumed by deployment/deploy.py
#
# Usage:
#   export PROJECT_ID=nprod-demo REGION=us-central1
#   ./infra/setup.sh
# =============================================================================
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
GCLOUD="${GCLOUD:-gcloud}"
MCP_SERVICE="${MCP_SERVICE:-mcp-anatel}"
MCP_REGION="${MCP_REGION:-us-central1}"
SA_NAME="${SA_NAME:-anatel-advisor-sa}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
STAGING_BUCKET="${STAGING_BUCKET:-${PROJECT_ID}-anatel-advisor-staging}"
REPORTS_BUCKET="${REPORTS_BUCKET:-${PROJECT_ID}-anatel-advisor-reports}"
SECRET_ID="${SECRET_ID:-anatel-mcp-url}"
ARMOR_TEMPLATE_ID="${ARMOR_TEMPLATE_ID:-anatel-advisor-guardrails}"
DATASTORE_ID="${DATASTORE_ID:-anatel-methodology-kb}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

g() { "${GCLOUD}" --project="${PROJECT_ID}" --quiet "$@"; }
log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. APIs
log "Enabling APIs"
g services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  dlp.googleapis.com \
  modelarmor.googleapis.com \
  cloudtrace.googleapis.com \
  telemetry.googleapis.com \
  logging.googleapis.com \
  discoveryengine.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com

PROJECT_NUMBER="$(g projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

# ---------------------------------------------------------------- 2. Service account
log "Service account ${SA_EMAIL}"
if ! g iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  g iam service-accounts create "${SA_NAME}" \
    --display-name="Anatel Telecom Advisor (Agent Engine runtime)"
fi

# ---------------------------------------------------------------- 3. IAM
log "Project-level IAM (least privilege)"
for role in \
  roles/aiplatform.user \
  roles/dlp.user \
  roles/modelarmor.user \
  roles/cloudtrace.agent \
  roles/logging.logWriter \
  roles/monitoring.metricWriter \
  roles/discoveryengine.viewer \
  roles/serviceusage.serviceUsageConsumer; do
  g projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" --role="${role}" --condition=None >/dev/null
done

log "Cloud Run invoker on ${MCP_SERVICE}"
# Prefer a resource-level binding (least privilege). Fall back to project level when the
# caller lacks run.services.setIamPolicy on the service.
if ! g run services add-iam-policy-binding "${MCP_SERVICE}" --region="${MCP_REGION}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/run.invoker >/dev/null 2>&1; then
  echo "Service-level binding not permitted; granting roles/run.invoker at project level."
  g projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" --role=roles/run.invoker --condition=None >/dev/null
fi

# ---------------------------------------------------------------- 4. Secret Manager
log "Secret ${SECRET_ID} (MCP URL)"
MCP_URL="$(g run services describe "${MCP_SERVICE}" --region="${MCP_REGION}" --format='value(status.url)')/mcp"
if ! g secrets describe "${SECRET_ID}" >/dev/null 2>&1; then
  g secrets create "${SECRET_ID}" --replication-policy=automatic
fi
CURRENT="$(g secrets versions access latest --secret="${SECRET_ID}" 2>/dev/null || true)"
if [[ "${CURRENT}" != "${MCP_URL}" ]]; then
  printf '%s' "${MCP_URL}" | g secrets versions add "${SECRET_ID}" --data-file=-
fi
# Least privilege: accessor on THIS secret only; project-level fallback if the caller
# cannot set IAM on the secret.
if ! g secrets add-iam-policy-binding "${SECRET_ID}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null 2>&1; then
  echo "Secret-level binding not permitted; granting secretAccessor at project level."
  g projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor --condition=None >/dev/null
fi

# ---------------------------------------------------------------- 5. Buckets
log "Buckets"
for bucket in "${STAGING_BUCKET}" "${REPORTS_BUCKET}"; do
  if ! g storage buckets describe "gs://${bucket}" >/dev/null 2>&1; then
    g storage buckets create "gs://${bucket}" --location="${REGION}" \
      --uniform-bucket-level-access --public-access-prevention \
      --default-storage-class=STANDARD
  fi
  g storage buckets update "gs://${bucket}" --versioning \
    --update-labels=app=anatel-advisor,managed-by=infra-setup >/dev/null
done
g storage buckets add-iam-policy-binding "gs://${REPORTS_BUCKET}" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/storage.objectCreator >/dev/null

# ---------------------------------------------------------------- 6. Model Armor
log "Model Armor template ${ARMOR_TEMPLATE_ID}"
if ! g model-armor templates describe "${ARMOR_TEMPLATE_ID}" --location="${REGION}" >/dev/null 2>&1; then
  g model-armor templates create "${ARMOR_TEMPLATE_ID}" --location="${REGION}" \
    --pi-and-jailbreak-filter-settings-enforcement=enabled \
    --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above \
    --malicious-uri-filter-settings-enforcement=enabled \
    --basic-config-filter-enforcement=enabled \
    --rai-settings-filters='[{"filterType":"HATE_SPEECH","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"HARASSMENT","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"DANGEROUS","confidenceLevel":"MEDIUM_AND_ABOVE"},{"filterType":"SEXUALLY_EXPLICIT","confidenceLevel":"MEDIUM_AND_ABOVE"}]' \
    --template-metadata-log-sanitize-operations
fi
ARMOR_TEMPLATE="projects/${PROJECT_ID}/locations/${REGION}/templates/${ARMOR_TEMPLATE_ID}"

# ---------------------------------------------------------------- 7. Vertex AI Search
log "Vertex AI Search data store ${DATASTORE_ID}"
TOKEN="$("${GCLOUD}" auth print-access-token)"
DE_API="https://discoveryengine.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/collections/default_collection"
hdr=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -H "x-goog-user-project: ${PROJECT_ID}")
if ! curl -sf "${hdr[@]}" "${DE_API}/dataStores/${DATASTORE_ID}" >/dev/null; then
  curl -sf "${hdr[@]}" -X POST "${DE_API}/dataStores?dataStoreId=${DATASTORE_ID}" -d '{
    "displayName": "Anatel methodology knowledge base",
    "industryVertical": "GENERIC",
    "solutionTypes": ["SOLUTION_TYPE_SEARCH"],
    "contentConfig": "CONTENT_REQUIRED"
  }' >/dev/null
  echo "Waiting for data store creation..."; sleep 20
fi
g storage cp "${ROOT_DIR}"/docs/knowledge/*.txt "gs://${STAGING_BUCKET}/knowledge/"
curl -sf "${hdr[@]}" -X POST "${DE_API}/dataStores/${DATASTORE_ID}/branches/default_branch/documents:import" -d "{
  \"gcsSource\": {\"inputUris\": [\"gs://${STAGING_BUCKET}/knowledge/*.txt\"], \"dataSchema\": \"content\"},
  \"reconciliationMode\": \"FULL\"
}" >/dev/null
DATASTORE="projects/${PROJECT_ID}/locations/global/collections/default_collection/dataStores/${DATASTORE_ID}"

# ---------------------------------------------------------------- 8. Outputs
ENV_FILE="${ROOT_DIR}/deployment/environments/${PROJECT_ID}.env"
log "Writing ${ENV_FILE#"${ROOT_DIR}"/} (non-secret, commit it)"
mkdir -p "$(dirname "${ENV_FILE}")"
cat > "${ENV_FILE}" <<EOF
# Non-secret environment config (resource names) generated by infra/setup.sh.
# Safe to commit: secrets live in Secret Manager.
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=${REGION}
AGENT_SERVICE_ACCOUNT=${SA_EMAIL}
STAGING_BUCKET=gs://${STAGING_BUCKET}
REPORTS_BUCKET=${REPORTS_BUCKET}
MCP_URL_SECRET_ID=${SECRET_ID}
MODEL_ARMOR_TEMPLATE=${ARMOR_TEMPLATE}
VERTEX_SEARCH_DATASTORE=${DATASTORE}
EOF
cat "${ENV_FILE}"
log "Done. Next: make deploy"
