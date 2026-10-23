from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel

from src.infrastructure.memory_cache import memory_cache

router = APIRouter(tags=["Health"])


class HealthStatus(BaseModel):
    status: str
    service: str = "mcp-anatel"


class ReadinessStatus(BaseModel):
    status: str
    service: str = "mcp-anatel"
    mode: str = "in-memory-http"
    fallback_ready: bool = True
    cache: dict[str, Any]


@router.get("/healthz", status_code=status.HTTP_200_OK, response_model=HealthStatus)
async def liveness() -> HealthStatus:
    """
    Liveness probe: Indica se a aplicação está ativa no Cloud Run.
    """
    return HealthStatus(status="alive")


@router.get("/readyz", status_code=status.HTTP_200_OK, response_model=ReadinessStatus)
async def readiness() -> ReadinessStatus:
    """
    Readiness probe: Verifica a prontidão do cache em memória (RAM) e do motor Polars.
    """
    return ReadinessStatus(
        status="ready",
        cache=memory_cache.stats(),
    )
