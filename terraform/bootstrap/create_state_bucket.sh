#!/usr/bin/env bash
# Creates the Terraform remote-state bucket (chicken-and-egg: cannot live in the
# configuration it stores). Versioned, uniform access, public access prevented.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-us-central1}"
GCLOUD="${GCLOUD:-gcloud}"
BUCKET="gs://${PROJECT_ID}-tfstate"
if ! "${GCLOUD}" storage buckets describe "${BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  "${GCLOUD}" storage buckets create "${BUCKET}" --project="${PROJECT_ID}" --location="${REGION}" \
    --uniform-bucket-level-access --public-access-prevention
fi
"${GCLOUD}" storage buckets update "${BUCKET}" --project="${PROJECT_ID}" --versioning \
  --update-labels=app=anatel-advisor,managed-by=bootstrap >/dev/null
echo "State bucket ready: ${BUCKET}"
