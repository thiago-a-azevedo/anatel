import io
import logging
import zipfile
from collections.abc import Callable
from typing import Any

import httpx
import polars as pl

from src.config import settings
from src.infrastructure.fallback_seed import (
    FALLBACK_CKAN_PACKAGES,
    build_fallback_indicadores_rede,
    build_fallback_pesquisa_satisfacao,
    build_fallback_reclamacoes_ida,
    build_fallback_rqual_iqs,
)
from src.infrastructure.memory_cache import memory_cache

logger = logging.getLogger(__name__)


class AnatelHttpClient:
    """Async HTTP client for Anatel's open-data portal / CKAN API, fully in memory.

    ZIP/CSV payloads are unpacked from ``io.BytesIO`` straight into Polars DataFrames
    (no disk writes). Every read falls back to the embedded seed snapshot so the
    service stays resilient and within the Gemini Enterprise action timeout.
    """

    def __init__(self, timeout_seconds: float = settings.http_timeout_seconds) -> None:
        self._timeout = timeout_seconds

    async def _try_fetch_csv_from_url(
        self,
        url: str,
        required_columns: set[str],
    ) -> pl.DataFrame | None:
        """Downloads a CSV or ZIP from Anatel in memory and validates the expected columns.

        Returns ``None`` (caller falls back to the seed) on any error or schema mismatch.
        """
        if not settings.enable_live_http_fetch:
            return None

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "mcp-anatel/0.1.0 (+https://www.anatel.gov.br/dadosabertos)"},
            ) as client:
                response = await client.get(url)
                if response.status_code != 200 or not response.content:
                    return None

                raw_bytes = response.content
                if url.lower().endswith(".zip") or raw_bytes[:4] == b"PK\x03\x04":
                    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                        if not csv_names:
                            return None
                        # Prefer the most recent CSV in the archive listing
                        target_csv = sorted(csv_names)[-1]
                        with zf.open(target_csv) as csv_file:
                            csv_bytes = csv_file.read()
                else:
                    csv_bytes = raw_bytes

                df = pl.read_csv(
                    io.BytesIO(csv_bytes),
                    separator=";",
                    ignore_errors=True,
                    try_parse_dates=False,
                    infer_schema_length=1000,
                )
                normalized_cols = {c.strip().lower() for c in df.columns}
                if required_columns.issubset(normalized_cols):
                    return df
                return None
        except Exception as exc:
            logger.info(
                "anatel_live_fetch_failed_using_seed",
                extra={
                    "event": "anatel_live_fetch_failed_using_seed",
                    "url": url,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

    async def _get_or_load_dataframe(
        self,
        cache_key: str,
        url: str,
        required_columns: set[str],
        fallback_builder: Callable[[], pl.DataFrame],
    ) -> tuple[pl.DataFrame, str]:
        """RAM cache first; on a miss, live HTTP read, then the in-memory seed fallback."""
        cached = memory_cache.get(cache_key)
        if cached is not None:
            return cached

        live_df = await self._try_fetch_csv_from_url(url, required_columns)
        if live_df is not None:
            memory_cache.set(cache_key, live_df, source_type="http_direto_anatel")
            return live_df, "http_direto_anatel"

        fallback_df = fallback_builder()
        memory_cache.set(cache_key, fallback_df, source_type="fallback_seed_ram")
        return fallback_df, "fallback_seed_ram"

    async def get_rqual_iqs_df(self) -> tuple[pl.DataFrame, str]:
        return await self._get_or_load_dataframe(
            cache_key="df_rqual_iqs",
            url=settings.anatel_rqual_zip_url,
            required_columns={"ano_mes", "servico", "operadora", "uf", "nota_iqs", "selo_rqual"},
            fallback_builder=build_fallback_rqual_iqs,
        )

    async def get_indicadores_rede_df(self) -> tuple[pl.DataFrame, str]:
        return await self._get_or_load_dataframe(
            cache_key="df_indicadores_rede",
            url=settings.anatel_rqual_zip_url,
            required_columns={"ano_mes", "servico", "operadora", "uf", "indicador", "valor_medido"},
            fallback_builder=build_fallback_indicadores_rede,
        )

    async def get_reclamacoes_ida_df(self) -> tuple[pl.DataFrame, str]:
        return await self._get_or_load_dataframe(
            cache_key="df_reclamacoes_ida",
            url=settings.anatel_reclamacoes_zip_url,
            required_columns={"ano_mes", "servico", "operadora", "uf", "total_reclamacoes", "nota_ida"},
            fallback_builder=build_fallback_reclamacoes_ida,
        )

    async def get_pesquisa_satisfacao_df(self) -> tuple[pl.DataFrame, str]:
        return await self._get_or_load_dataframe(
            cache_key="df_pesquisa_satisfacao",
            url=settings.anatel_satisfacao_zip_url,
            required_columns={"ano", "servico", "operadora", "uf", "nota_isg"},
            fallback_builder=build_fallback_pesquisa_satisfacao,
        )

    async def search_ckan_datasets(
        self,
        termo_busca: str = "qualidade rqual consumidor",
        limite: int = 10,
    ) -> tuple[list[dict[str, Any]], str]:
        """Queries Anatel's CKAN API (``package_search``) with a fallback to the embedded
        catalog of Consumer & Quality datasets."""
        if settings.enable_live_http_fetch:
            try:
                async with httpx.AsyncClient(
                    timeout=min(self._timeout, 6.0),
                    follow_redirects=True,
                ) as client:
                    resp = await client.get(
                        f"{settings.anatel_ckan_api_url}/package_search",
                        params={"q": termo_busca, "rows": min(limite, 25)},
                    )
                    if resp.status_code == 200:
                        payload = resp.json()
                        results = payload.get("result", {}).get("results", [])
                        if results:
                            parsed = []
                            for pkg in results[:limite]:
                                resources = pkg.get("resources", [])
                                first_url = resources[0].get("url", "") if resources else ""
                                parsed.append(
                                    {
                                        "id": pkg.get("id", ""),
                                        "name": pkg.get("name", ""),
                                        "title": pkg.get("title", ""),
                                        "notes": (pkg.get("notes") or "")[:300],
                                        "organization": (pkg.get("organization") or {}).get(
                                            "title", "Anatel"
                                        ),
                                        "url": first_url or settings.anatel_paineis_base_url,
                                        "format": resources[0].get("format", "CSV/ZIP")
                                        if resources
                                        else "CSV/ZIP",
                                    }
                                )
                            return parsed, "http_direto_anatel"
            except Exception as exc:
                logger.info(
                    "ckan_live_search_failed_using_seed",
                    extra={
                        "event": "ckan_live_search_failed_using_seed",
                        "termo_busca": termo_busca,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )

        term_tokens = [t.lower() for t in termo_busca.split() if len(t) > 2]
        filtered = []
        for item in FALLBACK_CKAN_PACKAGES:
            haystack = f"{item['title']} {item['notes']} {item['name']}".lower()
            if not term_tokens or any(tok in haystack for tok in term_tokens):
                filtered.append(item)
        return (filtered or FALLBACK_CKAN_PACKAGES)[:limite], "fallback_seed_ram"


anatel_http_client = AnatelHttpClient()
