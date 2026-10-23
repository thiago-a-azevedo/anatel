#!/usr/bin/env bash
# =============================================================================
# CI/CD identity (gcloud IaC, idempotent): keyless GitHub Actions -> Google Cloud.
#
# Creates:
#   1. Deployer service account `anatel-advisor-deployer` (least privilege for
#      eval + deploy + e2e; it can NOT change IAM or infrastructure).
#   2. Workload Identity Federation pool + GitHub OIDC provider restricted to ONE
#      repository (attribute condition), and the binding that lets that repo
#      impersonate the deployer SA. No JSON keys are ever created.
#   3. Lets the deployer SA act as the Agent Engine runtime SA (actAs) so it can
#      deploy the agent with that identity.
#   4. Prints the GitHub repository variables to configure.
#
# Usage:
#   PROJECT_ID=nprod-demo GITHUB_REPO=owner/repo ./infra/setup_cicd.sh
# =============================================================================
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
GITHUB_REPO="${GITHUB_REPO:?Set GITHUB_REPO (owner/repo)}"
GCLOUD="${GCLOUD:-gcloud}"
POOL_ID="${POOL_ID:-github-pool}"
PROVIDER_ID="${PROVIDER_ID:-github-oidc}"
DEPLOYER="anatel-advisor-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME="anatel-advisor-sa@${PROJECT_ID}.iam.gserviceaccount.com"

g() { "${GCLOUD}" --project="${PROJECT_ID}" --quiet "$@"; }
log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

g services enable iamcredentials.googleapis.com sts.googleapis.com cloudbuild.googleapis.com >/dev/null
PROJECT_NUMBER="$(g projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

# ---------------------------------------------------------------- 1. Deployer SA
log "Deployer service account ${DEPLOYER}"
if ! g iam service-accounts describe "${DEPLOYER}" >/dev/null 2>&1; then
  g iam service-accounts create anatel-advisor-deployer \
    --display-name="Anatel Advisor CI/CD deployer (eval, deploy, e2e)"
fi
# Least privilege for the pipeline: run the agent for eval/e2e and manage the
# Agent Engine instance. No IAM admin, no infra admin.
for role in \
  roles/aiplatform.user \
  roles/secretmanager.secretAccessor \
  roles/run.invoker \
  roles/modelarmor.user \
  roles/dlp.user \
  roles/discoveryengine.viewer \
  roles/logging.logWriter \
  roles/serviceusage.serviceUsageConsumer; do
  g projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER}" --role="${role}" --condition=None >/dev/null
done

# Cloud Build's metadata server has no identity endpoint, so the pipeline mints the
# MCP ID token through IAM Credentials generateIdToken on ITSELF, using the narrow
# OpenID token creator role (ID tokens only, no access tokens). Prefer a binding on
# the deployer SA itself; fall back to project level when SA IAM cannot be set.
if ! g iam service-accounts add-iam-policy-binding "${DEPLOYER}" \
  --member="serviceAccount:${DEPLOYER}" --role=roles/iam.serviceAccountOpenIdTokenCreator >/dev/null 2>&1; then
  echo "SA-level binding not permitted; granting serviceAccountOpenIdTokenCreator at project level."
  g projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER}" --role=roles/iam.serviceAccountOpenIdTokenCreator --condition=None >/dev/null
fi

# Cloud Build with a user-specified SA: read the uploaded source, write artifacts.
SOURCE_BUCKET="gs://${PROJECT_ID}_cloudbuild"
g storage buckets describe "${SOURCE_BUCKET}" >/dev/null 2>&1 || \
  g storage buckets create "${SOURCE_BUCKET}" --location=US --uniform-bucket-level-access
g storage buckets add-iam-policy-binding "${SOURCE_BUCKET}" \
  --member="serviceAccount:${DEPLOYER}" --role=roles/storage.objectViewer >/dev/null
g storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-anatel-advisor-staging" \
  --member="serviceAccount:${DEPLOYER}" --role=roles/storage.objectCreator >/dev/null

# ---------------------------------------------------------------- 2. actAs runtime SA
log "Allow deployer to deploy as ${RUNTIME}"
if ! g iam service-accounts add-iam-policy-binding "${RUNTIME}" \
  --member="serviceAccount:${DEPLOYER}" --role=roles/iam.serviceAccountUser >/dev/null 2>&1; then
  echo "SA-level binding not permitted; granting serviceAccountUser at project level"
  echo "(broader: deployer can act as any SA in the project - tighten when an admin can set SA IAM)."
  g projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER}" --role=roles/iam.serviceAccountUser --condition=None >/dev/null
fi

# ---------------------------------------------------------------- 3. WIF
log "Workload Identity Federation pool ${POOL_ID}"
if ! g iam workload-identity-pools describe "${POOL_ID}" --location=global >/dev/null 2>&1; then
  if ! g iam workload-identity-pools create "${POOL_ID}" --location=global \
    --display-name="GitHub Actions"; then
    echo "WARNING: cannot create the WIF pool (needs roles/iam.workloadIdentityPoolAdmin)."
    echo "         GitHub Actions CD stays disabled; Cloud Build CD (cloudbuild.yaml) still works."
    exit 0
  fi
fi
log "GitHub OIDC provider ${PROVIDER_ID} (restricted to ${GITHUB_REPO})"
if ! g iam workload-identity-pools providers describe "${PROVIDER_ID}" \
  --workload-identity-pool="${POOL_ID}" --location=global >/dev/null 2>&1; then
  g iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool="${POOL_ID}" --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
fi
PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"
log "Bind ${GITHUB_REPO} -> ${DEPLOYER}"
if ! g iam service-accounts add-iam-policy-binding "${DEPLOYER}" \
  --member="${PRINCIPAL}" --role=roles/iam.workloadIdentityUser >/dev/null 2>&1; then
  echo "WARNING: could not bind workloadIdentityUser on ${DEPLOYER}. Ask a project admin to run:"
  echo "         gcloud iam service-accounts add-iam-policy-binding ${DEPLOYER} --member='${PRINCIPAL}' --role=roles/iam.workloadIdentityUser --project=${PROJECT_ID}"
fi

MCP_AUDIENCE="$(g run services describe mcp-anatel --region=us-central1 --format='value(status.url)')"
PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
log "Configure these GitHub repository variables (Settings > Secrets and variables > Actions > Variables):"
cat <<EOF
  GCP_PROJECT_ID   = ${PROJECT_ID}
  GCP_WIF_PROVIDER = ${PROVIDER}
  GCP_DEPLOY_SA    = ${DEPLOYER}
  MCP_AUDIENCE     = ${MCP_AUDIENCE}

Or with the GitHub CLI:
  gh variable set GCP_PROJECT_ID   --repo ${GITHUB_REPO} --body '${PROJECT_ID}'
  gh variable set GCP_WIF_PROVIDER --repo ${GITHUB_REPO} --body '${PROVIDER}'
  gh variable set GCP_DEPLOY_SA    --repo ${GITHUB_REPO} --body '${DEPLOYER}'
  gh variable set MCP_AUDIENCE     --repo ${GITHUB_REPO} --body '${MCP_AUDIENCE}'

Then create the 'production' environment (Settings > Environments) and add
yourself as a required reviewer to gate deployments.
EOF
