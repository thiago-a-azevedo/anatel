import argparse
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from src import __version__
from src.api.health import router as health_router
from src.api.mcp_server import mcp
from src.config import settings
from src.core.exceptions import register_exception_handlers
from src.core.logging import setup_logging
from src.core.tracing import configure_tracing

setup_logging(settings.log_level)
configure_tracing()  # no-op outside Cloud Run unless ENABLE_CLOUD_TRACE=true


class NormalizeMcpTrailingSlashMiddleware:
    """Serves both ``POST /mcp`` and ``POST /mcp/`` without a 307 redirect.

    Gemini Enterprise's Custom MCP Server handshake does not follow redirects.
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


def create_app() -> FastAPI:
    """Builds the ASGI application (FastAPI + StreamableHTTP MCP mounted at /mcp).

    A factory (instead of module-level wiring) so each application instance owns its
    own ``StreamableHTTPSessionManager`` - the manager can only be started once, and
    tests build isolated instances.
    """
    # host="0.0.0.0", stateless_http=True and json_response=True keep the transport
    # compatible with Cloud Run (.run.app) and Gemini Enterprise Custom MCP Server.
    mcp_http_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host="0.0.0.0",
    )
    session_manager = mcp.session_manager  # the manager created by the call above

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        """Runs the StreamableHTTP session manager for the lifetime of the ASGI app."""
        async with session_manager.run():
            yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
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

    # Health probes required by Cloud Run
    app.include_router(health_router)

    @app.get("/")
    async def root() -> dict[str, object]:
        return {
            "service": settings.app_name,
            "version": __version__,
            "environment": settings.environment,
            "mcp_endpoint": "/mcp",
            "transport": "StreamableHTTP (stateless JSON-RPC)",
            "gemini_enterprise_compatible": True,
            "health_probes": {"liveness": "/healthz", "readiness": "/readyz"},
        }

    # Mount StreamableHTTP (/mcp) at the root, after the explicit FastAPI routes
    app.mount("/", mcp_http_app)
    return app


app = create_app()


def run_cli() -> None:
    """Command-line entrypoint (``mcp-anatel``).

    * ``--transport stdio``: MCP over stdin/stdout for local clients (Antigravity, Claude, Cursor).
    * ``--transport streamable-http``: HTTP/ASGI server via uvicorn on ``$PORT`` (Cloud Run / Gemini Enterprise).
    """
    parser = argparse.ArgumentParser(description="Anatel MCP server - Consumer & Quality (RQUAL/IQS)")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport: 'stdio' (local) or 'streamable-http' (Cloud Run / Gemini Enterprise)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind host in streamable-http mode (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help="HTTP port in streamable-http mode (default: $PORT or 8080)",
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
