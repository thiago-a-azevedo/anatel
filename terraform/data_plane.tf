# =============================================================================
# Data plane: secret, buckets, Model Armor, Vertex AI Search knowledge base
# =============================================================================

# ---------------------------------------------------------------- Secret Manager
resource "google_secret_manager_secret" "mcp_url" {
  secret_id = local.secret_id
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "mcp_url" {
  secret      = google_secret_manager_secret.mcp_url.id
  secret_data = "${local.mcp_url}/mcp"
}

# ---------------------------------------------------------------- Buckets
resource "google_storage_bucket" "staging" {
  name                        = local.staging_bucket
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_buckets
  versioning {
    enabled = true
  }
  lifecycle_rule {
    condition {
      num_newer_versions = 5
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "reports" {
  name                        = local.reports_bucket
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_buckets
  versioning {
    enabled = true
  }
  # Data minimization: approved reports expire.
  lifecycle_rule {
    condition {
      age = var.reports_retention_days
    }
    action {
      type = "Delete"
    }
  }
}

# Runtime may only CREATE report objects (no read/list/delete).
resource "google_storage_bucket_iam_member" "runtime_reports_writer" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectCreator"
  member = local.runtime_sa
}

# Deployer archives CI artifacts (e2e results) in the staging bucket.
resource "google_storage_bucket_iam_member" "deployer_staging" {
  for_each = toset(["roles/storage.objectCreator", "roles/storage.legacyBucketReader"])
  bucket   = google_storage_bucket.staging.name
  role     = each.value
  member   = local.deployer_sa
}

# ---------------------------------------------------------------- Model Armor
resource "google_model_armor_template" "guardrails" {
  location    = var.region
  template_id = local.armor_id

  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
    sdp_settings {
      basic_config {
        filter_enforcement = "ENABLED"
      }
    }
    rai_settings {
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }
  }

  template_metadata {
    log_sanitize_operations = true
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------- Vertex AI Search
resource "google_discovery_engine_data_store" "methodology" {
  location          = "global"
  data_store_id     = local.datastore_id
  display_name      = "Anatel methodology knowledge base"
  industry_vertical = "GENERIC"
  content_config    = "CONTENT_REQUIRED"
  solution_types    = ["SOLUTION_TYPE_SEARCH"]

  # Matches the API default explicitly; omitting it forces a replacement.
  document_processing_config {
    default_parsing_config {
      digital_parsing_config {}
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_object" "knowledge" {
  for_each = fileset("${path.module}/../docs/knowledge", "*.txt")
  bucket   = google_storage_bucket.staging.name
  name     = "knowledge/${each.value}"
  source   = "${path.module}/../docs/knowledge/${each.value}"
}

# Document ingestion has no Terraform resource: re-import whenever the knowledge
# files change (content hash), so the index never drifts from the repository.
data "google_client_config" "current" {}

resource "terraform_data" "knowledge_import" {
  triggers_replace = {
    content   = join(",", [for o in google_storage_bucket_object.knowledge : o.md5hash])
    datastore = google_discovery_engine_data_store.methodology.name
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    # Short-lived token from the provider's own credentials (not stored in state).
    environment = {
      TOKEN = data.google_client_config.current.access_token
    }
    command = <<-EOT
      set -euo pipefail
      curl -sSf -X POST \
        -H "Authorization: Bearer $${TOKEN}" -H "Content-Type: application/json" \
        -H "x-goog-user-project: ${var.project_id}" \
        "https://discoveryengine.googleapis.com/v1/${google_discovery_engine_data_store.methodology.name}/branches/default_branch/documents:import" \
        -d '{"gcsSource":{"inputUris":["gs://${google_storage_bucket.staging.name}/knowledge/*.txt"],"dataSchema":"content"},"reconciliationMode":"FULL"}' >/dev/null
      echo "Knowledge base import started for ${google_discovery_engine_data_store.methodology.name}"
    EOT
  }
}
