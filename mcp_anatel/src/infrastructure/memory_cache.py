import threading
import time
from dataclasses import dataclass
from typing import Any

import polars as pl

from src.config import settings


@dataclass
class CacheEntry:
    dataframe: pl.DataFrame
    source_type: str  # "http_direto_anatel" | "fallback_seed_ram"
    created_at: float
    expires_at: float


class InMemoryDataFrameCache:
    """
    Cache thread-safe 100% em memória (RAM) com TTL para armazenar DataFrames Polars
    já filtrados/padronizados sem qualquer escrita em disco ou banco local.
    """

    def __init__(self, ttl_seconds: int = settings.cache_ttl_seconds) -> None:
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> tuple[pl.DataFrame, str] | None:
        """Retorna (DataFrame, source_type) se presente e dentro do TTL."""
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if now >= entry.expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            origin = "cache_ram_http" if entry.source_type == "http_direto_anatel" else entry.source_type
            return entry.dataframe, origin

    def set(self, key: str, df: pl.DataFrame, source_type: str, ttl_override: int | None = None) -> None:
        """Armazena um Polars DataFrame em memória RAM com TTL."""
        ttl = ttl_override if ttl_override is not None else self._ttl_seconds
        now = time.monotonic()
        with self._lock:
            self._store[key] = CacheEntry(
                dataframe=df,
                source_type=source_type,
                created_at=now,
                expires_at=now + ttl,
            )

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            active_keys = [k for k, v in self._store.items() if now < v.expires_at]
            return {
                "active_entries": len(active_keys),
                "keys": active_keys,
                "hits": self._hits,
                "misses": self._misses,
                "ttl_seconds": self._ttl_seconds,
            }


# Instância singleton em memória do processo
memory_cache = InMemoryDataFrameCache()
