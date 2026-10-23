# Security Policy

## Reporting a vulnerability
Please do **not** open public issues for security problems. Report them privately via
GitHub Security Advisories ("Report a vulnerability" on the repository's Security tab).

## Security design
| Area | Control |
|---|---|
| Identity | Dedicated runtime service account (`anatel-advisor-sa`) on Agent Engine; no service-account keys anywhere. CI uses Workload Identity Federation. |
| Least privilege | Resource-level bindings where possible (`run.invoker` on the MCP service, `secretAccessor` on one secret, `objectCreator` on the reports bucket). `infra/setup.sh` falls back to project level only when the operator cannot set resource IAM, and says so. |
| Secrets | MCP endpoint in Secret Manager. Developer overrides (`ANATEL_MCP_URL`, `MCP_ID_TOKEN`) are **ignored** on managed runtimes. |
| Service-to-service auth | Private Cloud Run MCP; Google-signed OIDC ID tokens with the service URL as audience, cached and refreshed. |
| Prompt security | Model Armor (prompt injection/jailbreak, malicious URLs, RAI, SDP) on prompts and responses + deterministic local rules. `GUARDRAILS_FAIL_MODE=closed` blocks turns when Model Armor is unreachable. |
| Tool safety | Client-side Pydantic validation of every MCP call; human confirmation (`require_confirmation=True`) before the only write action (export to GCS); sanitized object names. |
| Data protection | Cloud DLP redaction of PII in logs and before long-term memory; buckets with uniform access, public-access prevention and versioning; OTel GenAI message capture disabled. |
| Supply chain | Bounded dependency ranges, Dependabot, `pip-audit` and `gitleaks` in CI. |

## Known accepted vulnerabilities
| ID | Package | Why accepted | Exit criterion |
|---|---|---|---|
| CVE-2026-114603 | `opentelemetry-api` 1.42.1 (fixed in 1.45.1) | `google-adk` 2.12 pins `opentelemetry-api<=1.42.1`; upgrading breaks the framework. Exposure reduced: GenAI message-content capture is disabled and spans are exported only to Cloud Trace with the runtime identity. | Remove the `--ignore-vuln` flag in CI as soon as an ADK release allows `>=1.45.1` (Dependabot will propose it). |
