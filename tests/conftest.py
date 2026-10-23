"""Shared pytest fixtures: make the package importable without GCP access."""

import os

os.environ.setdefault("ANATEL_MCP_URL", "https://mcp-anatel.example.run.app")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("PII_REDACTION_MODE", "regex")
os.environ.setdefault("LOG_LEVEL", "WARNING")
