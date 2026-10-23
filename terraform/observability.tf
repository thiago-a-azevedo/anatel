# =============================================================================
# Observability as code: log-based metrics, alert policies, dashboard
# Built on the structured JSON logs emitted by anatel_advisor/plugins/* (agent,
# Agent Runtime) and mcp_anatel/src/core/observability.py (MCP server, Cloud Run).
# =============================================================================

locals {
  agent_logs = "resource.type=\"aiplatform.googleapis.com/ReasoningEngine\""
  mcp_logs   = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.mcp_service_name}\""

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

# ------------------------------------------------- MCP server (Cloud Run) metrics
resource "google_logging_metric" "mcp_tool_errors" {
  name        = "mcp_anatel/tool_errors"
  description = "Anatel MCP server: tools/call that returned isError or raised (mcp_tool_outcome logs)."
  filter      = "${local.mcp_logs} AND jsonPayload.event=\"mcp_tool_outcome\" AND jsonPayload.status!=\"success\""
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

resource "google_logging_metric" "mcp_tool_latency" {
  name            = "mcp_anatel/tool_latency_ms"
  description     = "Anatel MCP server: tools/call latency by tool and data origin (live HTTP, RAM cache or seed fallback)."
  filter          = "${local.mcp_logs} AND jsonPayload.event=\"mcp_tool_outcome\" AND jsonPayload.latency_ms>=0"
  value_extractor = "EXTRACT(jsonPayload.latency_ms)"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"
    labels {
      key        = "tool"
      value_type = "STRING"
    }
    labels {
      key        = "data_origin"
      value_type = "STRING"
    }
  }
  label_extractors = {
    tool        = "EXTRACT(jsonPayload.tool)"
    data_origin = "EXTRACT(jsonPayload.data_origin)"
  }
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 20
      growth_factor      = 2
      scale              = 1
    }
  }
}

resource "google_logging_metric" "mcp_fallback_reads" {
  name        = "mcp_anatel/fallback_reads"
  description = "Anatel MCP server: answers served from the embedded seed because the Anatel open-data portal was unreachable or timed out."
  filter      = "${local.mcp_logs} AND jsonPayload.event=\"mcp_tool_outcome\" AND jsonPayload.data_origin=\"fallback_seed_ram\""
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

resource "google_monitoring_alert_policy" "mcp_tool_errors" {
  display_name          = "Anatel MCP server - tool errors"
  combiner              = "OR"
  notification_channels = local.notification_channels
  documentation {
    content   = "The Anatel MCP server (Cloud Run `${var.mcp_service_name}`) is returning tool errors. Check `jsonPayload.event=\"mcp_tool_outcome\" AND jsonPayload.status!=\"success\"` and follow `logging.googleapis.com/trace` into Cloud Trace."
    mime_type = "text/markdown"
  }
  conditions {
    display_name = "MCP tool errors > 5 in 5 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.mcp_tool_errors.name}\" AND resource.type=\"cloud_run_revision\""
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

resource "google_monitoring_alert_policy" "mcp_fallback_reads" {
  display_name          = "Anatel MCP server - serving seed fallback (Anatel portal unreachable)"
  combiner              = "OR"
  notification_channels = local.notification_channels
  documentation {
    content   = "Most answers are coming from the embedded seed dataset: the Anatel open-data portal is down, slow or changed its files. Data is stale until live reads recover (`jsonPayload.data_origin=\"fallback_seed_ram\"`)."
    mime_type = "text/markdown"
  }
  conditions {
    display_name = "fallback reads > 20 in 15 min"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.mcp_fallback_reads.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 20
      duration        = "0s"
      aggregations {
        alignment_period     = "900s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
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
        },
        {
          width = 6, height = 4, yPos = 12
          widget = {
            title = "MCP server: tool latency p95 by data origin (ms)"
            xyChart = { dataSets = [{
              plotType   = "LINE"
              targetAxis = "Y1"
              timeSeriesQuery = { timeSeriesFilter = {
                filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.mcp_tool_latency.name}\""
                aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_PERCENTILE_95", crossSeriesReducer = "REDUCE_MAX", groupByFields = ["metric.label.data_origin"] }
              } }
            }] }
          }
        },
        {
          width = 6, height = 4, xPos = 6, yPos = 12
          widget = {
            title = "MCP server: tool errors and seed-fallback reads"
            xyChart = { dataSets = [
              { plotType = "STACKED_BAR", legendTemplate = "errors", targetAxis = "Y1",
                timeSeriesQuery = { timeSeriesFilter = {
                  filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.mcp_tool_errors.name}\""
                  aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_SUM", crossSeriesReducer = "REDUCE_SUM" }
              } } },
              { plotType = "LINE", legendTemplate = "fallback reads", targetAxis = "Y1",
                timeSeriesQuery = { timeSeriesFilter = {
                  filter      = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.mcp_fallback_reads.name}\""
                  aggregation = { alignmentPeriod = "300s", perSeriesAligner = "ALIGN_SUM", crossSeriesReducer = "REDUCE_SUM" }
              } } }
            ] }
          }
        },
        {
          width = 12, height = 4, yPos = 16
          widget = {
            title     = "MCP server: tool intent / outcome (log stream)"
            logsPanel = { filter = "${local.mcp_logs} AND jsonPayload.event=(\"mcp_tool_intent\" OR \"mcp_tool_outcome\")", resourceNames = ["projects/${var.project_id}"] }
          }
        }
      ]
    }
  })
}
