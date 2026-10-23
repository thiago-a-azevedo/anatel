#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Deploys the Custom MCP Server (mcp-anatel) to Google Cloud Run
#  1. Dedicated, least-privilege runtime service account with telemetry-only
#     roles: Cloud Trace, Cloud Logging and Cloud Monitoring.
#  2. Source-based deploy (non-root container) with observability enabled:
#     ENABLE_CLOUD_TRACE=true -> MCP SDK spans exported to Cloud Trace, joined to
#     the ADK agent's trace through the `traceparent` propagated in `_meta`;
#     GOOGLE_CLOUD_PROJECT  -> log <-> trace correlation in Cloud Logging.
#  3. Cloud Run Invoker permission for the Gemini Enterprise service agent
#     (Discovery Engine). The ADK agent's identity receives the same permission
#     through Terraform (terraform/iam.tf), scoped to the service.
# ==============================================================================

GCLOUD="${GCLOUD:-gcloud}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${PROJECT_ID:-$(${GCLOUD} config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-mcp-anatel}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-mcp-anatel-sa}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: set PROJECT_ID (e.g. export PROJECT_ID=my-gcp-project)"
  exit 1
fi

RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> 1. Resolving PROJECT_NUMBER for ${PROJECT_ID}..."
PROJECT_NUMBER="$(${GCLOUD} projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
echo "    PROJECT_NUMBER: ${PROJECT_NUMBER}"

echo "==> 2. Ensuring the runtime service account ${RUNTIME_SA} (telemetry only)..."
if ! ${GCLOUD} iam service-accounts describe "${RUNTIME_SA}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  ${GCLOUD} iam service-accounts create "${RUNTIME_SA_NAME}" \
    --project "${PROJECT_ID}" \
    --display-name "mcp-anatel runtime (Cloud Run)" \
    --description "Identity of the Anatel MCP server; writes traces, logs and metrics only."
fi

# IAM is eventually consistent: a freshly created service account can take a few
# seconds before bindings accept it. Retry with backoff before giving up.
bind_role() {
  local role="$1" attempt
  for attempt in 1 2 3 4 5 6; do
    if ${GCLOUD} projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="${role}" \
        --condition=None \
        --quiet >/dev/null 2>&1; then
      return 0
    fi
    echo "    binding ${role} not accepted yet (attempt ${attempt}/6); waiting for IAM propagation..."
    sleep $((attempt * 5))
  done
  echo "Error: could not grant ${role} to ${RUNTIME_SA}" >&2
  return 1
}
for role in roles/cloudtrace.agent roles/logging.logWriter roles/monitoring.metricWriter; do
  bind_role "${role}"
done

echo "==> 3. Deploying ${SERVICE_NAME} to Cloud Run (${REGION})..."
${GCLOUD} run deploy "${SERVICE_NAME}" \
  --source "${SCRIPT_DIR}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --platform managed \
  --service-account "${RUNTIME_SA}" \
  --no-allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 60s \
  --min-instances 0 \
  --max-instances 5 \
  --set-env-vars "ENVIRONMENT=production,LOG_LEVEL=INFO,CACHE_TTL_SECONDS=3600,HTTP_TIMEOUT_SECONDS=12.0,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},ENABLE_CLOUD_TRACE=true"

SERVICE_URL="$(${GCLOUD} run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --region "${REGION}" --format="value(status.url)")"

echo "==> 4. Granting Cloud Run Invoker (roles/run.invoker) to the Gemini Enterprise service agent..."
DISCOVERY_SA="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com"

${GCLOUD} projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="${DISCOVERY_SA}" \
  --role="roles/run.invoker" \
  --condition=None \
  --quiet >/dev/null

echo ""
echo "=============================================================================="
echo "DEPLOY COMPLETE"
echo "Cloud Run service URL    : ${SERVICE_URL}"
echo "Custom MCP endpoint      : ${SERVICE_URL}/mcp"
echo "Health check             : ${SERVICE_URL}/healthz"
echo "Readiness check          : ${SERVICE_URL}/readyz"
echo "Runtime service account  : ${RUNTIME_SA}"
echo ""
echo "Observability:"
echo "  Logs   : resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND jsonPayload.event=\"mcp_tool_outcome\""
echo "  Traces : Cloud Trace -> span 'tools/call <tool>' (service.name=mcp-anatel), child of the ADK agent's 'MCP send tools/call' span"
echo ""
echo "Google Cloud console -> Gemini Enterprise -> Data stores -> Create data store:"
echo "  1. Select 'Custom MCP Server'"
echo "  2. Enter the HTTPS URL: ${SERVICE_URL}/mcp"
echo "  3. Under Authentication, select 'Cloud Run integration'"
echo "  4. Once active, open 'Actions' -> 'Reload custom actions' and enable the 7 tools."
echo "=============================================================================="
