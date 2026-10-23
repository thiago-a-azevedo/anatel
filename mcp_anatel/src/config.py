from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, injected as environment variables by Cloud Run.

    The service runs 100% in memory (RAM): no local database or disk writes.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "mcp-anatel"
    environment: str = "production"
    port: int = 8080
    log_level: str = "INFO"

    # Observability (Cloud Logging + Cloud Trace)
    # - google_cloud_project: required to correlate logs <-> traces
    #   (field logging.googleapis.com/trace = projects/<id>/traces/<trace_id>)
    # - enable_cloud_trace: None = automatic (on when running on Cloud Run, via K_SERVICE)
    google_cloud_project: str = ""
    enable_cloud_trace: bool | None = None
    otel_service_name: str = "mcp-anatel"

    # In-memory (RAM) cache and response limits for Gemini Enterprise / the ADK agent
    cache_ttl_seconds: int = 3600
    http_timeout_seconds: float = 12.0
    default_max_rows: int = 25
    max_allowed_rows: int = 50
    enable_live_http_fetch: bool = True

    # Anatel open-data portal / CKAN endpoints
    anatel_ckan_api_url: str = "https://www.anatel.gov.br/dadosabertos/api/3/action"
    anatel_paineis_base_url: str = "https://www.anatel.gov.br/dadosabertos/paineis_de_dados"
    anatel_rqual_zip_url: str = (
        "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/qualidade/qualidade_rqual.zip"
    )
    anatel_reclamacoes_zip_url: str = (
        "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/consumidor/reclamacoes_contexto.zip"
    )
    anatel_satisfacao_zip_url: str = (
        "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/consumidor/pesquisa_satisfacao.zip"
    )


settings = Settings()
