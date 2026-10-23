"""Unit-test fixtures: make the package importable offline (fake, non-routable MCP URL).

Scoped to tests/unit only: the eval and e2e suites must use the real Secret Manager value.
"""

import os

os.environ.setdefault("ANATEL_MCP_URL", "https://mcp-anatel.example.run.app")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("PII_REDACTION_MODE", "regex")
os.environ.setdefault("LOG_LEVEL", "WARNING")
