#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Deploy do Custom MCP Server (mcp-anatel) no Google Cloud Run
#  1. Service account de runtime dedicada (least privilege) com permissão apenas
#     para telemetria: Cloud Trace, Cloud Logging e Cloud Monitoring.
#  2. Deploy (source-based, container non-root) com observabilidade habilitada:
#     ENABLE_CLOUD_TRACE=true -> spans do SDK MCP exportados para o Cloud Trace,
#     ligados ao trace do agente ADK pelo `traceparent` propagado em `_meta`;
#     GOOGLE_CLOUD_PROJECT  -> correlação log <-> trace no Cloud Logging.
#  3. Permissão Cloud Run Invoker para o Service Agent do Gemini Enterprise
#     (Discovery Engine). A identidade do agente ADK recebe a mesma permissão via
#     Terraform (terraform/iam.tf), com escopo no serviço.
# ==============================================================================

GCLOUD="${GCLOUD:-gcloud}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${PROJECT_ID:-$(${GCLOUD} config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-mcp-anatel}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-mcp-anatel-sa}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Erro: Defina a variável PROJECT_ID (ex: export PROJECT_ID=meu-projeto-gcp)"
  exit 1
fi

RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> 1. Obtendo PROJECT_NUMBER do projeto ${PROJECT_ID}..."
PROJECT_NUMBER="$(${GCLOUD} projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
echo "    PROJECT_NUMBER: ${PROJECT_NUMBER}"

echo "==> 2. Garantindo a service account de runtime ${RUNTIME_SA} (telemetria apenas)..."
if ! ${GCLOUD} iam service-accounts describe "${RUNTIME_SA}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  ${GCLOUD} iam service-accounts create "${RUNTIME_SA_NAME}" \
    --project "${PROJECT_ID}" \
    --display-name "mcp-anatel runtime (Cloud Run)" \
    --description "Identidade do servidor MCP da Anatel; escreve apenas traces, logs e metricas."
fi
for role in roles/cloudtrace.agent roles/logging.logWriter roles/monitoring.metricWriter; do
  ${GCLOUD} projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

echo "==> 3. Realizando deploy do ${SERVICE_NAME} no Google Cloud Run (${REGION})..."
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

echo "==> 4. Concedendo permissão Cloud Run Invoker (roles/run.invoker) ao Service Agent do Gemini Enterprise..."
DISCOVERY_SA="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com"

${GCLOUD} projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="${DISCOVERY_SA}" \
  --role="roles/run.invoker" \
  --condition=None \
  --quiet >/dev/null

echo ""
echo "=============================================================================="
echo "DEPLOY CONCLUÍDO COM SUCESSO!"
echo "URL do Serviço Cloud Run : ${SERVICE_URL}"
echo "Endpoint Custom MCP      : ${SERVICE_URL}/mcp"
echo "Health Check             : ${SERVICE_URL}/healthz"
echo "Readiness Check          : ${SERVICE_URL}/readyz"
echo "Runtime service account  : ${RUNTIME_SA}"
echo ""
echo "Observabilidade:"
echo "  Logs   : resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${SERVICE_NAME}\" AND jsonPayload.event=\"mcp_tool_outcome\""
echo "  Traces : Cloud Trace -> span 'tools/call <tool>' (service.name=mcp-anatel), filho do span 'MCP send tools/call' do agente ADK"
echo ""
echo "No Console do Google Cloud -> Gemini Enterprise -> Data Stores -> Create Data Store:"
echo "  1. Selecione 'Custom MCP Server'"
echo "  2. Informe a URL HTTPS: ${SERVICE_URL}/mcp"
echo "  3. Em Authentication, selecione 'Cloud Run integration'"
echo "  4. Após ativo, acesse 'Actions' -> 'Reload custom actions' e habilite as 7 tools."
echo "=============================================================================="
