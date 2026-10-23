from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações da aplicação injetadas como variáveis de ambiente pelo Cloud Run.
    Opera 100% em memória (RAM) sem dependência de banco de dados local.
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

    # Observabilidade (Cloud Logging + Cloud Trace)
    # - google_cloud_project: necessário para correlacionar logs <-> traces
    #   (campo logging.googleapis.com/trace = projects/<id>/traces/<trace_id>)
    # - enable_cloud_trace: None = automático (ligado no Cloud Run, via K_SERVICE)
    google_cloud_project: str = ""
    enable_cloud_trace: bool | None = None
    otel_service_name: str = "mcp-anatel"

    # Cache em memória (RAM) e limites de resposta para o Gemini Enterprise
    cache_ttl_seconds: int = 3600
    http_timeout_seconds: float = 12.0
    default_max_rows: int = 25
    max_allowed_rows: int = 50
    enable_live_http_fetch: bool = True

    # Endpoints do Portal de Dados Abertos / CKAN da Anatel
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
