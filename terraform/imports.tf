# =============================================================================
# One-time adoption of resources originally created by the legacy gcloud scripts.
# Import blocks are idempotent: once a resource is in state they are no-ops.
# Safe to delete this file after the first successful `terraform apply`.
# (IAM member resources are additive and need no import.)
# =============================================================================

import {
  to = google_service_account.runtime
  id = "projects/${var.project_id}/serviceAccounts/anatel-advisor-sa@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_service_account.deployer
  id = "projects/${var.project_id}/serviceAccounts/anatel-advisor-deployer@${var.project_id}.iam.gserviceaccount.com"
}

import {
  to = google_secret_manager_secret.mcp_url
  id = "projects/${var.project_id}/secrets/anatel-mcp-url"
}

import {
  to = google_storage_bucket.staging
  id = "${var.project_id}-anatel-advisor-staging"
}

import {
  to = google_storage_bucket.reports
  id = "${var.project_id}-anatel-advisor-reports"
}

import {
  to = google_model_armor_template.guardrails
  id = "projects/${var.project_id}/locations/${var.region}/templates/anatel-advisor-guardrails"
}

import {
  to = google_discovery_engine_data_store.methodology
  id = "projects/${var.project_id}/locations/global/collections/default_collection/dataStores/anatel-methodology-kb"
}
