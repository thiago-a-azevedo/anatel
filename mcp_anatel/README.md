# 📡 `mcp-anatel` — Servidor MCP de Consumidor e Qualidade (RQUAL / IQS / IDA / Satisfação)

Servidor **Model Context Protocol (MCP)** desenvolvido em **Python 3.12+ (FastAPI + FastMCP + Polars)** para consulta em memória (RAM) aos dados abertos da **Anatel** sobre **Consumidor e Qualidade**, projetado para ser **100% compatível com o Gemini Enterprise App (Custom MCP Server)** via protocolo `StreamableHTTP` (`/mcp`) no **Google Cloud Run**, além de suportar execução local via `stdio`.

---

## 🎯 Pilares de Dados Cobertos

1. **Selo de Qualidade RQUAL e IQS (`consultar_rqual_iqs`)**
   * Selos de Qualidade (`A`, `B`, `C`, `D`, `E`) e nota do **IQS (Índice de Qualidade do Serviço)** por operadora, serviço (`SMP`, `SCM`, `STFC`), UF e município.
2. **Indicadores Operacionais de Qualidade de Rede (`consultar_indicadores_rede`)**
   * Cumprimento de velocidade de **download** e **upload** (%), **latência** (ms), **jitter** (ms), **perda de pacotes** (%) e **disponibilidade** (%) frente às metas regulatórias da Anatel.
3. **Reclamações Anatel Consumidor e IDA (`consultar_reclamacoes_ida`)**
   * Volume de reclamações, índice por 1.000 acessos, principais motivos, taxa de resolução (%), prazo médio de resposta (dias) e nota do **IDA (Índice de Desempenho no Atendimento)**.
4. **Pesquisa de Satisfação e Qualidade Percebida (`consultar_pesquisa_satisfacao`)**
   * Nota do **ISG (Índice de Satisfação Geral)** e avaliações de **Funcionamento**, **Atendimento** e **Cobrança/Recarga**.
5. **Comparador Consolidado de Operadoras (`comparar_operadoras`)**
   * Cruzamento automático em memória dos 4 pilares para classificar operadoras em uma UF/município e serviço.
6. **Catálogo CKAN (`buscar_datasets_ckan_anatel`) & Glossário Regulatório (`consultar_glossario_metodologia_anatel`)**
   * Descoberta de pacotes no portal de dados abertos da Anatel e dicionário completo da Resolução nº 717/2019 (RQUAL) e Resolução nº 632/2014 (RGC).

---

## ⚙️ Arquitetura 100% In-Memory e Compatibilidade Gemini Enterprise

* **Sem Banco de Dados Local:** Os dados são processados em memória via **Polars** com cache TTL em RAM (`CACHE_TTL_SECONDS=3600`) e fallback instantâneo embarcado caso o servidor da Anatel oscile ou exceda o timeout de Actions do Gemini Enterprise.
* **Protocolo `StreamableHTTP` Stateless (`/mcp`):** Configurado com `stateless_http=True` e `json_response=True`, sem redirecionamentos `307` entre `/mcp` e `/mcp/`.
* **Normalização Inteligente de Entidades:** Aceita termos em linguagem natural (`"fibra"` $\rightarrow$ `SCM`, `"celular"` $\rightarrow$ `SMP`, `"Telefonica"` $\rightarrow$ `VIVO`, `"São Paulo"` $\rightarrow$ `SP`).

---

## 🚀 Como Executar Localmente

### 1. Instalar dependências (via `uv` ou `venv`)
```bash
uv sync --all-extras
# Ou com venv padrão:
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

### 2. Executar os testes automatizados
```bash
.venv/bin/pytest -v
```

### 3. Iniciar em modo HTTP (`StreamableHTTP` em `http://localhost:8080/mcp`)
```bash
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8080
```

### 4. Iniciar em modo `stdio` (para Antigravity / Claude Desktop / Cursor)
```bash
.venv/bin/python -m src.main --transport stdio
```

---

## 🔭 Observabilidade (Cloud Logging + Cloud Trace)

O servidor segue o mesmo contrato de telemetria do agente ADK (`anatel_advisor/`), para que **uma única requisição possa ser seguida da pergunta do usuário até a leitura do dataset da Anatel**:

| Pilar | Implementação |
|---|---|
| **Logs JSON estruturados** | [`src/core/logging.py`](src/core/logging.py): uma linha JSON por registro com `severity`, `sourceLocation`, `logging.googleapis.com/trace` + `spanId` (campos nativos do Cloud Logging) e todos os campos `extra=` em `jsonPayload`. Em modo `stdio` os logs vão para `stderr` (stdout fica limpo para o MCP). |
| **Intent vs. outcome** | [`src/core/observability.py`](src/core/observability.py): middleware do `MCPServer` que emite `mcp_tool_intent` (antes) e `mcp_tool_outcome` (depois) para cada `tools/call`, com `request_id`, latência, linhas retornadas e `data_origin` (`http_direto_anatel`, `cache_ram_http` ou `fallback_seed_ram`), e anota o span com `anatel.mcp.*`. |
| **Tracing distribuído** | O SDK `mcp` 2.x já cria um span `SERVER` por mensagem, **parenteado no `traceparent` W3C recebido em `params._meta`** (injetado automaticamente pelo cliente MCP do agente ADK). [`src/core/tracing.py`](src/core/tracing.py) instala o exporter do Cloud Trace (automático no Cloud Run ou `ENABLE_CLOUD_TRACE=true`), então o span `tools/call <tool>` aparece **dentro do mesmo trace** do agente (`invocation → agent_run → execute_tool → MCP send tools/call`). |
| **Redação de PII** | `PiiRedactionFilter` (regex: e-mail, CPF, CNPJ, telefone, cartão) aplicado à mensagem, aos args e a todo campo `extra=` antes da serialização. |

Variáveis: `GOOGLE_CLOUD_PROJECT` (correlação log ↔ trace), `ENABLE_CLOUD_TRACE` (`true`/`false`; padrão: ligado no Cloud Run), `LOG_LEVEL`.
Métricas, alertas e dashboard (`mcp_anatel/tool_errors`, `tool_latency_ms`, `fallback_reads`) são provisionados em [`terraform/observability.tf`](../terraform/observability.tf).

Consulta útil no Cloud Logging:
```text
resource.type="cloud_run_revision" AND resource.labels.service_name="mcp-anatel"
AND jsonPayload.event="mcp_tool_outcome" AND jsonPayload.data_origin="fallback_seed_ram"
```

---

## ☁️ Deploy no Google Cloud Run + Configuração no Gemini Enterprise App

Execute o script automatizado em [`scripts/deploy_cloud_run.sh`](scripts/deploy_cloud_run.sh) (ou `make mcp-deploy PROJECT_ID=<projeto>` na raiz do repositório):

```bash
chmod +x scripts/deploy_cloud_run.sh
PROJECT_ID="seu-projeto-gcp" REGION="us-central1" ./scripts/deploy_cloud_run.sh
```

O script realiza:
1. Criação (idempotente) da service account de runtime `mcp-anatel-sa` com papéis apenas de telemetria (`roles/cloudtrace.agent`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`).
2. Build e deploy do container multi-stage `non-root` no **Google Cloud Run** (privado, `--no-allow-unauthenticated`) com `ENABLE_CLOUD_TRACE=true` e `GOOGLE_CLOUD_PROJECT` definidos.
3. Concessão do papel `roles/run.invoker` ao Service Agent oficial do Gemini Enterprise (`service-<PROJECT_NUMBER>@gcp-sa-discoveryengine.iam.gserviceaccount.com`). A identidade do agente ADK recebe a mesma permissão via Terraform (`terraform/iam.tf`), com escopo no serviço.

### Passo a Passo no Console do Gemini Enterprise:
1. No Console do Google Cloud, acesse **Gemini Enterprise** $\rightarrow$ **Data stores** $\rightarrow$ **Create data store**.
2. Selecione **Custom MCP Server**.
3. Informe a URL HTTPS do serviço com o sufixo `/mcp`:
   ```text
   https://mcp-anatel-<hash>-uc.a.run.app/mcp
   ```
4. Em **Authentication**, selecione **Cloud Run integration**.
5. Após a criação, abra o Data Store $\rightarrow$ aba **Actions** $\rightarrow$ clique em **Reload custom actions** e habilite as 7 Actions.
