locals {
  app = "anatel-advisor"

  labels = {
    app         = local.app
    environment = var.environment
    managed-by  = "terraform"
  }

  apis = toset([
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "dlp.googleapis.com",
    "modelarmor.googleapis.com",
    "cloudtrace.googleapis.com",
    "telemetry.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "discoveryengine.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "billingbudgets.googleapis.com",
  ])

  staging_bucket = "${var.project_id}-${local.app}-staging"
  reports_bucket = "${var.project_id}-${local.app}-reports"
  secret_id      = "anatel-mcp-url"
  armor_id       = "${local.app}-guardrails"
  datastore_id   = "anatel-methodology-kb"

  # Cloud Run exposes two URLs (legacy hash-based and project-number based); pin the
  # deterministic project-number URL so the secret and ID-token audience are stable.
  mcp_url = one([for u in data.google_cloud_run_v2_service.mcp.urls : u if strcontains(u, data.google_project.this.number)])

  runtime_sa  = "serviceAccount:${google_service_account.runtime.email}"
  deployer_sa = "serviceAccount:${google_service_account.deployer.email}"
}

data "google_project" "this" {
  project_id = var.project_id
}

# The MCP server is an existing, independently managed service.
data "google_cloud_run_v2_service" "mcp" {
  name     = var.mcp_service_name
  location = var.mcp_region
}

resource "google_project_service" "apis" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}
