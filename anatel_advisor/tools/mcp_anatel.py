"""Connection to the Anatel MCP server (Cloud Run) as an ADK ``McpToolset``.

The MCP server (``mcp-anatel``) is a private Cloud Run service: every request must
carry a Google-signed OIDC ID token whose audience is the service URL, and the caller
must hold ``roles/run.invoker`` (granted to the Agent Engine identity by
Terraform (``terraform/``)).

The service URL is **not** hardcoded: it is read from Secret Manager
(``anatel-mcp-url``) through :func:`anatel_advisor.secrets.get_secret`.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from ..config import get_settings, is_managed_runtime
from ..secrets import get_secret

logger = logging.getLogger(__name__)

#: Every tool exposed by the Anatel MCP server, grouped by purpose.
ANATEL_DATA_TOOLS: list[str] = [
    "consultar_rqual_iqs",
    "consultar_indicadores_rede",
    "consultar_reclamacoes_ida",
    "consultar_pesquisa_satisfacao",
    "comparar_operadoras",
]
ANATEL_REFERENCE_TOOLS: list[str] = [
    "consultar_glossario_metodologia_anatel",
    "buscar_datasets_ckan_anatel",
]
ALL_ANATEL_TOOLS: list[str] = ANATEL_DATA_TOOLS + ANATEL_REFERENCE_TOOLS

_TOKEN_TTL_SECONDS = 45 * 60  # Google ID tokens live 60 min; refresh early.


class _IdTokenProvider:
    """Thread-safe cached provider of OIDC ID tokens for a Cloud Run audience."""

    def __init__(self, audience: str):
        self._audience = audience
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _fetch(self) -> str:
        # 1) Explicit override - developer machines / CI only, ignored in production.
        if os.getenv("MCP_ID_TOKEN") and not is_managed_runtime():
            return os.environ["MCP_ID_TOKEN"]
        # 2) Workload identity: Agent Engine / Cloud Run / GCE metadata server or a
        #    service-account key referenced by GOOGLE_APPLICATION_CREDENTIALS.
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            request = google.auth.transport.requests.Request()
            return google.oauth2.id_token.fetch_id_token(request, self._audience)
        except Exception as exc:  # noqa: BLE001
            logger.info("id_token_metadata_unavailable", extra={"error": str(exc)})
        # 2b) IAM Credentials generateIdToken for the ADC service account itself.
        #     Needed where the metadata identity endpoint is unavailable (e.g. Cloud
        #     Build). Requires roles/iam.serviceAccountOpenIdTokenCreator on itself.
        try:
            return self._fetch_via_iam_credentials()
        except Exception as exc:  # noqa: BLE001
            if is_managed_runtime():
                raise RuntimeError(
                    "Workload identity could not mint an ID token for the Anatel MCP "
                    f"server ({exc}). Check the Agent Engine service account."
                ) from exc
            logger.info("id_token_workload_identity_unavailable", extra={"error": str(exc)})
        # 3) Local developer fallback: end-user gcloud credentials (never in production).
        gcloud = shutil.which("gcloud")
        if gcloud:
            out = subprocess.run(
                [gcloud, "auth", "print-identity-token"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return out.stdout.strip()
        raise RuntimeError(
            "Could not obtain an ID token for the Anatel MCP server. Run "
            "'gcloud auth login' locally or deploy with a service account that has "
            "roles/run.invoker on the mcp-anatel Cloud Run service."
        )

    def _fetch_via_iam_credentials(self) -> str:
        import google.auth
        import google.auth.transport.requests
        from google.auth import impersonated_credentials

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        request = google.auth.transport.requests.Request()
        source, _ = google.auth.default(scopes=scopes)
        source.refresh(request)  # populates service_account_email on metadata creds
        email = getattr(source, "service_account_email", None)
        if not email or "@" not in email or email == "default":
            raise RuntimeError("ADC is not a service account; cannot use generateIdToken")
        target = impersonated_credentials.Credentials(
            source_credentials=source, target_principal=email, target_scopes=scopes
        )
        id_creds = impersonated_credentials.IDTokenCredentials(
            target, target_audience=self._audience, include_email=True
        )
        id_creds.refresh(request)
        return id_creds.token

    def get(self) -> str:
        with self._lock:
            if not self._token or time.time() >= self._expires_at:
                self._token = self._fetch()
                self._expires_at = time.time() + _TOKEN_TTL_SECONDS
            return self._token


def _resolve_mcp_url() -> str:
    url = get_secret(get_settings().mcp_url_secret_id, env_override="ANATEL_MCP_URL")
    return url if url.rstrip("/").endswith("/mcp") else url.rstrip("/") + "/mcp"


def build_anatel_toolset(tool_filter: list[str] | None = None) -> McpToolset:
    """Creates an ``McpToolset`` bound to the private Anatel MCP server.

    Args:
      tool_filter: Optional subset of tool names to expose to the agent. Each agent
        only receives the tools it needs (least privilege, smaller prompts).

    Returns:
      A configured :class:`McpToolset` that injects a fresh ID token on every
      request via ``header_provider``.
    """
    url = _resolve_mcp_url()
    parsed = urlparse(url)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    token_provider = _IdTokenProvider(audience)

    def _auth_headers(_ctx: ReadonlyContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {token_provider.get()}"}

    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=url,
            timeout=get_settings().mcp_timeout_seconds,
        ),
        tool_filter=tool_filter or ALL_ANATEL_TOOLS,
        header_provider=_auth_headers,
        tool_list_cache_ttl_seconds=600,
    )
