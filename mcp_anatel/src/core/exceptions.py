"""Domain exception and FastAPI exception handlers (structured, trace-correlated)."""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AnatelDataError(Exception):
    """Domain error while fetching or processing Anatel data."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the global exception handlers on the FastAPI application."""

    @app.exception_handler(AnatelDataError)
    async def anatel_data_error_handler(request: Request, exc: AnatelDataError) -> JSONResponse:
        logger.warning(
            "anatel_data_error",
            extra={"event": "anatel_data_error", "path": request.url.path, "error": exc.message},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "AnatelDataError",
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            extra={"event": "unhandled_exception", "path": request.url.path, "error_type": type(exc).__name__},
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "InternalServerError",
                # User-facing message stays in Portuguese (Brazilian end users).
                "message": "Ocorreu um erro interno ao processar a requisição no MCP Anatel.",
            },
        )
