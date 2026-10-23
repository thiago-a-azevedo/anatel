# Multi-stage build on python-slim + uv for fast, reproducible images
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-install-project --no-dev

# Final runtime image
FROM python:3.12-slim-bookworm

# Non-root user (corporate security baseline)
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup ./src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080

USER appuser

# Cloud Run injects $PORT (default 8080).
# One worker per instance so the in-memory (RAM) cache is shared by every request.
# --no-access-log: Cloud Run already logs every request (run.googleapis.com/requests);
# the app emits only structured JSON logs (intent/outcome per tool, trace-correlated).
CMD ["sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log"]
