import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AnatelDataError(Exception):
    """Exceção de domínio para falhas na consulta ou processamento de dados da Anatel."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers globais de exceção para a aplicação FastAPI."""

    @app.exception_handler(AnatelDataError)
    async def anatel_data_error_handler(request: Request, exc: AnatelDataError) -> JSONResponse:
        logger.warning(f"Erro de domínio Anatel em {request.url.path}: {exc.message}")
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
        logger.error(f"Erro inesperado em {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "InternalServerError",
                "message": "Ocorreu um erro interno ao processar a requisição no MCP Anatel.",
            },
        )
