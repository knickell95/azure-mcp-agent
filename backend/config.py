import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# Azure auth — service principal (leave blank to use az login instead)
AZURE_TENANT_ID: str = os.environ.get("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID: str = os.environ.get("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET: str = os.environ.get("AZURE_CLIENT_SECRET", "")
AZURE_SUBSCRIPTION_ID: str = os.environ.get("AZURE_SUBSCRIPTION_ID", "")

# Use az login credentials when no service principal secret is configured
AZ_LOGIN_MODE: bool = not bool(AZURE_CLIENT_SECRET)

MCP_IMAGE: str = os.environ.get("MCP_IMAGE", "mcr.microsoft.com/azure-sdk/azure-mcp:latest")


def _az_account() -> dict:
    """Return parsed output of `az account show`. Cached after first call."""
    if not hasattr(_az_account, "_cache"):
        try:
            result = subprocess.run(
                ["az", "account", "show", "--output", "json"],
                capture_output=True, text=True, check=True, timeout=10,
            )
            _az_account._cache = json.loads(result.stdout)
        except Exception:
            _az_account._cache = {}
    return _az_account._cache


def get_tenant_id() -> str:
    """Return tenant ID — from .env or az account show."""
    return AZURE_TENANT_ID or _az_account().get("tenantId", "")


def get_subscription_id() -> str:
    """Return subscription ID — from .env or az account show."""
    return AZURE_SUBSCRIPTION_ID or _az_account().get("id", "")
