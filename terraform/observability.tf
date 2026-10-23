# =============================================================================
# Observability as code: log-based metrics, alert policies, dashboard
# Built on the structured JSON logs emitted by anatel_advisor/plugins/*.
# =============================================================================

locals {
  agent_logs = "resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""

  notification_channels = var.alert_email == "" ? [] : [google_monitoring_notification_channel.email[0].id]
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  display_name = "Anatel Advisor alerts"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------- log-based metrics
resource "google_logging_metric" "guardrail_blocked" {
  name        = "anatel_advisor/guardrail_blocked"
  description = "User turns blocked by guardrails (local rules or Model Armor)."
  filter      = "${local.agent_logs} AND jsonPayload.message=\"guardrail_blocked\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "layer"
      value_type = "STRING"
    }
  }
  label_extractors = {
    layer = "EXTRACT(jsonPayload.layer)"
  }
}

resource "google_logging_metric" "tool_errors" {
  name        = "anatel_advisor/tool_errors"
  description = "Tool calls that failed (exception, MCP error or invalid arguments)."
  filter      = "${local.agent_logs} AND (jsonPayload.event=\"tool_error\" OR (jsonPayload.event=\"tool_outcome\" AND jsonPayload.status=\"error\"))"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key        = "tool"
      value_type = "STRING"
    }
  }
  label_extractors = {
    tool = "EXTRACT(jsonPayload.tool)"
  }
}

resource "google_logging_metric" "memory_failures" {
  name        = "anatel_advisor/memory_generation_failed"
  description = "Background Memory Bank generation failures."
  filter      = "${local.agent_logs} AND jsonPayload.message=\"memory_generation_failed\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }
}

resource "google_logging_metric" "tool_latency" {
  name            = "anatel_advisor/tool_latency_ms"
  description     = "Latency of tool calls (MCP and local tools), from tool_outcome logs."
  filter          = "${local.agent_logs} AND jsonPayload.event=\"tool_outcome\" AND jsonPayload.latency_ms>0"
  value_extractor = "EXTRACT(jsonPayload.latency_ms)"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"
    labels {
      key        = "tool"
      value_type = "STRING"
    }
  }
  label_extractors = {
    tool = "EXTRACT(jsonPayload.tool)"
  }
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 2
      scale              = 10
    }
  }
}

# ---------------------------------------------------------------- alert policies
resource "google_monitoring_alert_policy" "tool_errors" {
  display_name          = "Anatel Advisor - tool errors"
  combiner              = "OR"
  notification_channels = local.notification_channels
  documentation {
    content   = "Tool calls are failing (MCP unreachable, auth or invalid arguments). Check `jsonPayload.event=\"tool_error\"` in Cloud Logging."
    mime_type = "text/markdown"
  }
  conditions {
    display_name = "tool errors > 5 in 5 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.tool_errors.name}\" AND resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "0s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "guardrail_spike" {
  display_name          = "Anatel Advisor - guardrail block spike"
  combiner              = "OR"
  notification_channels = local.notification_channels
  documentation {
    content   = "Unusual number of blocked prompts: possible abuse / prompt-injection campaign."
    mime_type = "text/markdown"
  }
  conditions {
    display_name = "blocked prompts > 10 in 5 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.guardrail_blocked.name}\" AND resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "0s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "memory_failures" {
  display_name          = "Anatel Advisor - memory generation failing"
  combiner              = "OR"
  notification_channels = local.notification_channels
  conditions {
    display_name = "any memory failure in 15 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.memory_failures.name}\" AND resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period     = "900s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "tool_latency" {
  display_name          = "Anatel Advisor - slow tools (p95)"
  combiner              = "OR"
  notification_channels = local.notification_channels
  conditions {
    display_name = "p95 tool latency > 10 s for 10 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.tool_latency.name}\" AND resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
      comparison      = "COMPARISON_GT"
      threshold_value = 10000
      duration        = "600s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }
}

# ---------------------------------------------------------------- dashboard
resource "google_monitoring_dashboard" "agent" {
  dashboard_json = jsonencode({
    displayName = "Anatel Telecom Advisor"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width = 6, height = 4
          widget = {
            title = "Tool errors by tool"
            xyChart = { dataSets = [{
              plotType   = "STACKED_BAR"
              targetAxis = "Y1"
              timeSeriesQuery = { timeSeriesFilter = {
                filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.tool_errors.name}\""
                aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_SUM", crossSeriesReducer = "REDUCE_SUM", groupByFields = ["metric.label.tool"] }
              } }
            }] }
          }
        },
        {
          width = 6, height = 4, xPos = 6
          widget = {
            title = "Tool latency p50 / p95 (ms)"
            xyChart = { dataSets = [
              { plotType = "LINE", legendTemplate = "p95", targetAxis = "Y1",
                timeSeriesQuery = { timeSeriesFilter = {
                  filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.tool_latency.name}\""
                  aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_PERCENTILE_95", crossSeriesReducer = "REDUCE_MAX" }
              } } },
              { plotType = "LINE", legendTemplate = "p50", targetAxis = "Y1",
                timeSeriesQuery = { timeSeriesFilter = {
                  filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.tool_latency.name}\""
                  aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_PERCENTILE_50", crossSeriesReducer = "REDUCE_MAX" }
              } } }
            ] }
          }
        },
        {
          width = 6, height = 4, yPos = 4
          widget = {
            title = "Guardrail blocks by layer"
            xyChart = { dataSets = [{
              plotType   = "STACKED_BAR"
              targetAxis = "Y1"
              timeSeriesQuery = { timeSeriesFilter = {
                filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.guardrail_blocked.name}\""
                aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_SUM", crossSeriesReducer = "REDUCE_SUM", groupByFields = ["metric.label.layer"] }
              } }
            }] }
          }
        },
        {
          width = 6, height = 4, xPos = 6, yPos = 4
          widget = {
            title = "Memory generation failures"
            xyChart = { dataSets = [{
              plotType   = "LINE"
              targetAxis = "Y1"
              timeSeriesQuery = { timeSeriesFilter = {
                filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.memory_failures.name}\""
                aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_SUM", crossSeriesReducer = "REDUCE_SUM" }
              } }
            }] }
          }
        },
        {
          width = 12, height = 4, yPos = 8
          widget = {
            title     = "Agent errors (log stream)"
            logsPanel = { filter = "${local.agent_logs} AND severity>=ERROR", resourceNames = ["projects/${var.project_id}"] }
          }
        }
      ]
    }
  })
}
