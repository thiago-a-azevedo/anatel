# 📡 `mcp-anatel` — Consumer & Quality MCP server (RQUAL / IQS / IDA / Satisfaction)

**Model Context Protocol (MCP)** server written in **Python 3.12+ (FastAPI + `MCPServer` + Polars)** that serves Anatel's **Consumer & Quality** open data entirely in memory (RAM). It is **100% compatible with Gemini Enterprise (Custom MCP Server)** through the `StreamableHTTP` transport (`/mcp`) on **Google Cloud Run**, is the data backend of the ADK agent in this repository (`anatel_advisor/`), and can also run locally over `stdio`.

> Tool, resource and prompt descriptions — as well as the data itself (glossary, summaries, tables) — are intentionally written in **Brazilian Portuguese**: they are consumed by the LLM and shown to Brazilian end users. Code documentation is in English, like the rest of the repository.

---

## 🎯 Data pillars

1. **RQUAL quality seal and IQS (`consultar_rqual_iqs`)**
   * Quality seals (`A`–`E`) and the **IQS (Índice de Qualidade do Serviço)** score by operator, service (`SMP`, `SCM`, `STFC`), state (UF) and municipality.
2. **Operational network-quality indicators (`consultar_indicadores_rede`)**
   * **Download** and **upload** speed compliance (%), **latency** (ms), **jitter** (ms), **packet loss** (%) and **availability** (%) against Anatel's regulatory targets.
3. **Consumer complaints and IDA (`consultar_reclamacoes_ida`)**
   * Complaint volume, complaints per 1,000 accesses, main reasons, resolution rate (%), average response time (days) and the **IDA (Índice de Desempenho no Atendimento)** score.
4. **Satisfaction and perceived-quality survey (`consultar_pesquisa_satisfacao`)**
   * **ISG (Índice de Satisfação Geral)** score plus the **Functioning**, **Customer service** and **Billing/Top-up** ratings.
5. **Consolidated operator comparison (`comparar_operadoras`)**
   * In-memory join of the 4 pillars to rank operators for a state/municipality and service.
6. **CKAN catalog (`buscar_datasets_ckan_anatel`) & regulatory glossary (`consultar_glossario_metodologia_anatel`)**
   * Package discovery on Anatel's open-data portal and the full dictionary of Resolution 717/2019 (RQUAL) and Resolution 632/2014 (RGC).

---

## ⚙️ Architecture: 100% in-memory, Gemini Enterprise compatible

* **No local database:** data is processed in memory with **Polars**, cached in RAM with a TTL (`CACHE_TTL_SECONDS=3600`) and backed by an embedded seed snapshot that answers instantly whenever Anatel's portal is slow or exceeds the Gemini Enterprise action timeout.
* **Stateless `StreamableHTTP` (`/mcp`):** `stateless_http=True` and `json_response=True`, with no `307` redirects between `/mcp` and `/mcp/`.
* **Entity normalization:** natural-language filters are accepted (`"fibra"` → `SCM`, `"celular"` → `SMP`, `"Telefonica"` → `VIVO`, `"São Paulo"` → `SP`).

Layout:

```
mcp_anatel/
├── src/api/            # FastAPI health probes + MCPServer (7 tools, 2 resources, 2 prompts)
├── src/application/    # AnatelService: Polars filtering, aggregation and Markdown tables
├── src/domain/         # response entities, alias normalizer, regulatory glossary
├── src/infrastructure/ # async HTTP client (ZIP/CSV -> Polars), RAM cache, seed fallback
├── src/core/           # JSON logging, tracing, intent/outcome middleware, exceptions
├── scripts/            # Cloud Run deployment
└── tests/              # 22 unit, StreamableHTTP protocol and observability tests
```

---

## 🚀 Running locally

From the repository root (shared virtualenv, see the root `Makefile`):

```bash
make install          # once
make mcp-test         # pytest mcp_anatel/tests -v
make mcp-run          # uvicorn on http://localhost:8080/mcp
```

Or standalone, from this directory:

```bash
uv sync --all-extras                       # or: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -v
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8080        # StreamableHTTP
.venv/bin/python -m src.main --transport stdio                    # stdio (Antigravity / Claude Desktop / Cursor)
```

---

## 🔭 Observability (Cloud Logging + Cloud Trace)

The server follows the same telemetry contract as the ADK agent (`anatel_advisor/`), so **a single request can be followed from the user's question to the Anatel dataset read**:

| Pillar | Implementation |
|---|---|
| **Structured JSON logging** | [`src/core/logging.py`](src/core/logging.py): one JSON line per record with `severity`, `sourceLocation`, `logging.googleapis.com/trace` + `spanId` (native Cloud Logging fields) and every `extra=` field in `jsonPayload`. In `stdio` mode logs go to `stderr` so stdout stays a clean MCP channel. |
| **Intent vs. outcome** | [`src/core/observability.py`](src/core/observability.py): `MCPServer` middleware that emits `mcp_tool_intent` (before) and `mcp_tool_outcome` (after) for every `tools/call`, with `request_id`, latency, rows returned and `data_origin` (`http_direto_anatel`, `cache_ram_http` or `fallback_seed_ram`), and annotates the span with `anatel.mcp.*` attributes. |
| **Distributed tracing** | The `mcp` 2.x SDK already opens one `SERVER` span per message, **parented on the W3C `traceparent` received in `params._meta`** (injected automatically by the ADK agent's MCP client). [`src/core/tracing.py`](src/core/tracing.py) installs the Cloud Trace exporter (automatic on Cloud Run, or `ENABLE_CLOUD_TRACE=true`), so the `tools/call <tool>` span shows up **inside the agent's trace** (`invocation → agent_run → execute_tool → MCP send tools/call`). |
| **PII redaction** | `PiiRedactionFilter` (regex: e-mail, CPF, CNPJ, phone, card) applied to the message, the args and every `extra=` field before serialization. |

Environment variables: `GOOGLE_CLOUD_PROJECT` (log ↔ trace correlation), `ENABLE_CLOUD_TRACE` (`true`/`false`; default: on when running on Cloud Run), `LOG_LEVEL`.
Metrics, alerts and dashboard tiles (`mcp_anatel/tool_errors`, `tool_latency_ms`, `fallback_reads`) are provisioned in [`terraform/observability.tf`](../terraform/observability.tf).

Useful Cloud Logging query:
```text
resource.type="cloud_run_revision" AND resource.labels.service_name="mcp-anatel"
AND jsonPayload.event="mcp_tool_outcome" AND jsonPayload.data_origin="fallback_seed_ram"
```

---

## ☁️ Deploying to Google Cloud Run + Gemini Enterprise setup

Run [`scripts/deploy_cloud_run.sh`](scripts/deploy_cloud_run.sh) (or `make mcp-deploy PROJECT_ID=<project>` from the repository root):

```bash
chmod +x scripts/deploy_cloud_run.sh
PROJECT_ID="your-gcp-project" REGION="us-central1" ./scripts/deploy_cloud_run.sh
```

The script:
1. Creates (idempotently) the runtime service account `mcp-anatel-sa` with telemetry-only roles (`roles/cloudtrace.agent`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`).
2. Builds and deploys the multi-stage, non-root container to **Cloud Run** (private, `--no-allow-unauthenticated`) with `ENABLE_CLOUD_TRACE=true` and `GOOGLE_CLOUD_PROJECT` set.
3. Grants `roles/run.invoker` to the Gemini Enterprise service agent (`service-<PROJECT_NUMBER>@gcp-sa-discoveryengine.iam.gserviceaccount.com`). The ADK agent's identity gets the same permission through Terraform (`terraform/iam.tf`), scoped to the service.

### Gemini Enterprise console steps
1. In the Google Cloud console, go to **Gemini Enterprise** → **Data stores** → **Create data store**.
2. Select **Custom MCP Server**.
3. Enter the service's HTTPS URL with the `/mcp` suffix:
   ```text
   https://mcp-anatel-<hash>-uc.a.run.app/mcp
   ```
4. Under **Authentication**, select **Cloud Run integration**.
5. After creation, open the data store → **Actions** tab → **Reload custom actions** and enable the 7 actions.
