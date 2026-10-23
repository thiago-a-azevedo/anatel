# Security Policy

## Reporting a vulnerability
Please do **not** open public issues for security problems. Report them privately via
GitHub Security Advisories ("Report a vulnerability" on the repository's Security tab).

## Security design
| Area | Control |
|---|---|
| Identity | Dedicated runtime SA (`anatel-advisor-sa`) on Agent Runtime (Gemini Enterprise Agent Platform), a separate deployer SA (`anatel-advisor-deployer`) for CI/CD and a telemetry-only SA (`mcp-anatel-sa`) for the MCP server on Cloud Run; no service-account keys anywhere. GitHub Actions authenticates with Workload Identity Federation restricted to this repository. |
| Separation of duties | The deployer can evaluate, deploy and smoke-test but cannot change IAM or create infrastructure (Terraform is admin-applied). Production deploys are gated by a GitHub `production` environment. |
| Least privilege | Resource-level bindings where possible (`run.invoker` on the MCP service, `secretAccessor` on one secret, `objectCreator` on the reports bucket). Terraform `iam_scope = "project"` is an explicit, reviewed fallback for operators who cannot set resource IAM. |
| Secrets | MCP endpoint in Secret Manager. Developer overrides (`ANATEL_MCP_URL`, `MCP_ID_TOKEN`) are **ignored** on managed runtimes. |
| Service-to-service auth | Private Cloud Run MCP; Google-signed OIDC ID tokens with the service URL as audience, cached and refreshed. |
| Prompt security | Model Armor (prompt injection/jailbreak, malicious URLs, RAI, SDP) on prompts and responses + deterministic local rules. `GUARDRAILS_FAIL_MODE=closed` blocks turns when Model Armor is unreachable. |
| Tool safety | Client-side Pydantic validation of every MCP call; human confirmation (`require_confirmation=True`) before the only write action (export to GCS); sanitized object names. |
| Data protection | Cloud DLP redaction of PII in logs and before long-term memory (regex scrubber on the MCP server logs); buckets with uniform access, public-access prevention and versioning. |
| Telemetry privacy | Telemetry carries ids, sizes, counts, latencies and statuses only. Message content is never copied into OTel spans or GenAI events: the deployment enables telemetry through `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY` (not the legacy `enable_tracing=True`, which forces content capture) and pins `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT` (the documented `EVENT_ONLY` opt-in would also log prompts, responses and `user.id`). |
| Supply chain | Bounded dependency ranges, Dependabot, `pip-audit` (agent and MCP server) and `gitleaks` in CI. |

## Known accepted vulnerabilities
| ID | Package | Why accepted | Exit criterion |
|---|---|---|---|
| CVE-2026-114603 | `opentelemetry-api` 1.42.1 (fixed in 1.45.1) | `google-adk` 2.12 pins `opentelemetry-api<=1.42.1`; upgrading breaks the framework. Exposure reduced: GenAI message-content capture is disabled and telemetry is exported only to Google Cloud Observability with the runtime identity. The MCP server resolves its own dependencies (`mcp_anatel/`) and is not affected. | Remove the `--ignore-vuln` flag in CI as soon as an ADK release allows `>=1.45.1` (Dependabot will propose it). |
