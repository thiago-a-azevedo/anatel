# Multi-stage build usando python-slim e uv para builds rápidos e reprodutíveis
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# Imagem final de execução
FROM python:3.12-slim-bookworm

# Cria usuário não-root (obrigatório pelas diretrizes de segurança corporativas)
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup ./src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080

USER appuser

# Cloud Run injeta $PORT dinamicamente (padrão 8080)
# 1 worker por instância garante compartilhamento do cache em memória (RAM)
# --no-access-log: o Cloud Run já registra cada requisição (run.googleapis.com/requests);
# a aplicação emite apenas logs JSON estruturados (intent/outcome por tool, correlacionados ao trace)
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log"]
