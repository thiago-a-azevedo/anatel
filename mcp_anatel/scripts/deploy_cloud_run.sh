#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Script de Deploy do Custom MCP Server (mcp-anatel) no Google Cloud Run
# e configuração de permissão IAM para o Gemini Enterprise (Discovery Engine)
# ==============================================================================

GCLOUD="${GCLOUD:-gcloud}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ID="${PROJECT_ID:-$(${GCLOUD} config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-mcp-anatel}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Erro: Defina a variável PROJECT_ID (ex: export PROJECT_ID=meu-projeto-gcp)"
  exit 1
fi

echo "==> 1. Obtendo PROJECT_NUMBER do projeto ${PROJECT_ID}..."
PROJECT_NUMBER="$(${GCLOUD} projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
echo "    PROJECT_NUMBER: ${PROJECT_NUMBER}"

echo "==> 2. Realizando deploy do ${SERVICE_NAME} no Google Cloud Run (${REGION})..."
${GCLOUD} run deploy "${SERVICE_NAME}" \
  --source "${SCRIPT_DIR}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --platform managed \
  --no-allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 60s \
  --min-instances 0 \
  --max-instances 5 \
  --set-env-vars "ENVIRONMENT=production,CACHE_TTL_SECONDS=3600,HTTP_TIMEOUT_SECONDS=12.0"

SERVICE_URL="$(${GCLOUD} run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --region "${REGION}" --format="value(status.url)")"

echo "==> 3. Concedendo permissão Cloud Run Invoker (roles/run.invoker) ao Service Agent do Gemini Enterprise..."
DISCOVERY_SA="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com"

${GCLOUD} projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="${DISCOVERY_SA}" \
  --role="roles/run.invoker" \
  --condition=None

echo ""
echo "=============================================================================="
echo "DEPLOY CONCLUÍDO COM SUCESSO!"
echo "URL do Serviço Cloud Run : ${SERVICE_URL}"
echo "Endpoint Custom MCP      : ${SERVICE_URL}/mcp"
echo "Health Check             : ${SERVICE_URL}/healthz"
echo "Readiness Check          : ${SERVICE_URL}/readyz"
echo ""
echo "No Console do Google Cloud -> Gemini Enterprise -> Data Stores -> Create Data Store:"
echo "  1. Selecione 'Custom MCP Server'"
echo "  2. Informe a URL HTTPS: ${SERVICE_URL}/mcp"
echo "  3. Em Authentication, selecione 'Cloud Run integration'"
echo "  4. Após ativo, acesse 'Actions' -> 'Reload custom actions' e habilite as 7 tools."
echo "=============================================================================="
