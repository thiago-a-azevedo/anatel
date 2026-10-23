import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.health import router as health_router
from src.api.mcp_server import mcp
from src.config import settings
from src.core.exceptions import register_exception_handlers
from src.core.logging import setup_logging

setup_logging(settings.log_level)

# Inicializa o ASGI app StreamableHTTP do MCPServer (rota padrão: /mcp)
# host="0.0.0.0", stateless_http=True e json_response=True garantem compatibilidade
# com Google Cloud Run (.run.app) e Gemini Enterprise Custom MCP Server
mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
)


class NormalizeMcpTrailingSlashMiddleware:
    """
    Garante que tanto POST /mcp quanto POST /mcp/ funcionem sem 307 Temporary Redirect,
    evitando falhas de handshake no Gemini Enterprise Custom MCP Server.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp/":
            scope = dict(scope)
            scope["path"] = "/mcp"
            if "raw_path" in scope:
                scope["raw_path"] = b"/mcp"
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida do SessionManager do StreamableHTTP MCP no Cloud Run."""
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Custom MCP Server (StreamableHTTP /mcp) para consulta em memória aos dados abertos "
        "da Anatel: Consumidor e Qualidade (RQUAL, IQS, Indicadores de Rede, Reclamações/IDA e Satisfação)."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(NormalizeMcpTrailingSlashMiddleware)
register_exception_handlers(app)

# Rotas de integridade obrigatórias para o Google Cloud Run
app.include_router(health_router)


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "environment": settings.environment,
        "mcp_endpoint": "/mcp",
        "transport": "StreamableHTTP (stateless JSON-RPC)",
        "gemini_enterprise_compatible": True,
        "health_probes": {"liveness": "/healthz", "readiness": "/readyz"},
    }


# Monta o StreamableHTTP (/mcp) na raiz após as rotas explícitas do FastAPI
app.mount("/", mcp_http_app)


def run_cli() -> None:
    """
    Entrypoint de linha de comando (`mcp-anatel`):
    - `--transport stdio`: Executa o servidor MCP via stdin/stdout para clientes locais (Antigravity, Claude, Cursor).
    - `--transport streamable-http`: Executa o servidor HTTP/ASGI via Uvicorn na porta $PORT (padrão Cloud Run / Gemini Enterprise).
    """
    parser = argparse.ArgumentParser(description="Servidor MCP Anatel - Consumidor e Qualidade (RQUAL/IQS)")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Protocolo de transporte MCP: 'stdio' (local) ou 'streamable-http' (Cloud Run / Gemini Enterprise)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host de bind quando em modo streamable-http (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help="Porta HTTP quando em modo streamable-http (default: $PORT ou 8080)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        setup_logging(settings.log_level, use_stderr=True)
        mcp.run(transport="stdio")
    else:
        setup_logging(settings.log_level, use_stderr=False)
        uvicorn.run("src.main:app", host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    run_cli()
