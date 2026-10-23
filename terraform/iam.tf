# =============================================================================
# Identities
#   runtime  - the Agent Runtime (Gemini Enterprise Agent Platform) workload identity
#   deployer - the CI/CD identity (eval, deploy, e2e; cannot change IAM/infra)
# No service-account keys are created anywhere.
# =============================================================================

resource "google_service_account" "runtime" {
  account_id   = "anatel-advisor-sa"
  display_name = "Anatel Telecom Advisor (Agent Engine runtime)"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account" "deployer" {
  account_id   = "anatel-advisor-deployer"
  display_name = "Anatel Advisor CI/CD deployer (eval, deploy, e2e)"
  depends_on   = [google_project_service.apis]
}

# ---------------------------------------------------------------- project roles
locals {
  runtime_project_roles = toset([
    "roles/aiplatform.user",                   # Gemini, Agent Platform Sessions, Memory Bank
    "roles/modelarmor.user",                   # prompt/response sanitization
    "roles/dlp.user",                          # PII redaction
    "roles/discoveryengine.viewer",            # Agent Search methodology knowledge base
    "roles/cloudtrace.agent",                  # OpenTelemetry spans
    "roles/logging.logWriter",                 # structured logs
    "roles/monitoring.metricWriter",           # runtime metrics
    "roles/serviceusage.serviceUsageConsumer", # quota project
  ])

  deployer_project_roles = toset([
    "roles/aiplatform.user", # create/update Agent Runtime, run eval
    "roles/modelarmor.user", # eval runs the agent locally
    "roles/dlp.user",
    "roles/discoveryengine.viewer",
    "roles/logging.logWriter", # Cloud Build logs
    "roles/serviceusage.serviceUsageConsumer",
  ])

  project_scope = var.iam_scope == "project"
}

resource "google_project_iam_member" "runtime" {
  for_each = local.runtime_project_roles
  project  = var.project_id
  role     = each.value
  member   = local.runtime_sa
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_project_roles
  project  = var.project_id
  role     = each.value
  member   = local.deployer_sa
}

# ---------------------------------------------------------------- resource-scoped roles
# Least privilege when iam_scope = "resource"; project-level fallback otherwise.

# Call the private MCP server.
resource "google_cloud_run_v2_service_iam_member" "mcp_invoker" {
  for_each = local.project_scope ? toset([]) : toset([local.runtime_sa, local.deployer_sa])
  name     = data.google_cloud_run_v2_service.mcp.name
  location = var.mcp_region
  role     = "roles/run.invoker"
  member   = each.value
}

# Read the MCP endpoint secret.
resource "google_secret_manager_secret_iam_member" "mcp_url_accessor" {
  for_each  = local.project_scope ? toset([]) : toset([local.runtime_sa, local.deployer_sa])
  secret_id = google_secret_manager_secret.mcp_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}

# Deployer deploys the agent AS the runtime SA.
resource "google_service_account_iam_member" "deployer_act_as_runtime" {
  count              = local.project_scope ? 0 : 1
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = local.deployer_sa
}

# Cloud Build has no metadata identity endpoint: the deployer mints the MCP ID token
# for ITSELF through IAM Credentials (ID tokens only, no access tokens).
resource "google_service_account_iam_member" "deployer_self_id_token" {
  count              = local.project_scope ? 0 : 1
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountOpenIdTokenCreator"
  member             = local.deployer_sa
}

locals {
  fallback_project_roles = local.project_scope ? {
    "runtime-run-invoker"          = { role = "roles/run.invoker", member = local.runtime_sa }
    "runtime-secret-accessor"      = { role = "roles/secretmanager.secretAccessor", member = local.runtime_sa }
    "deployer-run-invoker"         = { role = "roles/run.invoker", member = local.deployer_sa }
    "deployer-secret-accessor"     = { role = "roles/secretmanager.secretAccessor", member = local.deployer_sa }
    "deployer-sa-user"             = { role = "roles/iam.serviceAccountUser", member = local.deployer_sa }
    "deployer-openid-tokencreator" = { role = "roles/iam.serviceAccountOpenIdTokenCreator", member = local.deployer_sa }
  } : {}
}

resource "google_project_iam_member" "fallback" {
  for_each = local.fallback_project_roles
  project  = var.project_id
  role     = each.value.role
  member   = each.value.member
}
