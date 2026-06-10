"""
MCPBridge — singleton that owns the MCP server connection and exposes
async list_tools() / call_tool() methods to the rest of the app.

Two transport modes are supported:
  stdio  — spawns the Azure MCP Docker container as a subprocess (local dev)
  http   — connects to an Azure MCP sidecar via HTTP (Azure Container Apps)

Select the mode with the MCP_TRANSPORT env var (default: "stdio").
"""
import asyncio
import logging
import os
import tempfile
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import Tool

import config
from token_proxy import token_proxy

log = logging.getLogger(__name__)

_RECONNECT_ATTEMPTS = 3
_RECONNECT_DELAY = 2.0  # seconds
_fake_az_dir: tempfile.TemporaryDirectory | None = None


def _build_docker_args() -> list[str]:
    """Build the docker run argument list for the Azure MCP container (stdio mode only)."""
    args = [
        "run", "--rm", "-i",
        # Allow container to reach host services (token proxy, etc.)
        "--add-host=host.docker.internal:host-gateway",
    ]

    if config.AZ_LOGIN_MODE:
        # Mount a fake `az` script so AzureCliCredential inside the container
        # can obtain tokens from the host's `az login` session via our token proxy.
        assert _fake_az_dir is not None, "start() must be called before _build_docker_args()"
        fake_az_path = os.path.join(_fake_az_dir.name, "az")
        args += ["-v", f"{fake_az_path}:/usr/local/bin/az:ro"]

        sub_id = config.get_subscription_id()
        if sub_id:
            args += ["-e", f"AZURE_SUBSCRIPTION_ID={sub_id}"]
        tenant_id = config.get_tenant_id()
        if tenant_id:
            args += ["-e", f"AZURE_TENANT_ID={tenant_id}"]
    else:
        # Service principal credentials
        for var in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID",
                    "AZURE_CLIENT_SECRET", "AZURE_SUBSCRIPTION_ID"):
            val = getattr(config, var)
            if val:
                args += ["-e", f"{var}={val}"]

    args.append(config.MCP_IMAGE)
    return args


class MCPBridge:
    """
    Maintains a single MCP ClientSession and exposes tool operations.
    Thread-safe for concurrent async callers via an asyncio.Lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._session: ClientSession | None = None
        self._tools: list[Tool] = []
        self._exit_stack: AsyncExitStack | None = None

    async def start(self) -> None:
        """Initialize the MCP session. Call once at server startup."""
        global _fake_az_dir
        if config.MCP_TRANSPORT == "stdio" and config.AZ_LOGIN_MODE:
            token_proxy.start()
            _fake_az_dir = tempfile.TemporaryDirectory(prefix="azure-mcp-fake-az-")
            fake_az_path = os.path.join(_fake_az_dir.name, "az")
            token_proxy.write_fake_az_script(fake_az_path)
            log.info("Fake az script written to %s", fake_az_path)

        if config.MCP_TRANSPORT == "http":
            # The sidecar starts concurrently and may not be ready yet.
            # Retry for up to ~30 s; if still failing let the app bind to its
            # port anyway — call_tool() and list_tools() will reconnect on use.
            max_attempts = 10
            for attempt in range(1, max_attempts + 1):
                try:
                    await self._connect()
                    return
                except Exception as exc:
                    if attempt < max_attempts:
                        log.warning(
                            "MCP connect attempt %d/%d failed: %s — retrying in 3 s",
                            attempt, max_attempts, exc,
                        )
                        await asyncio.sleep(3)
                    else:
                        log.error(
                            "MCP connect failed after %d attempts — "
                            "app will start; retrying on first request",
                            max_attempts,
                        )
        else:
            await self._connect()

    async def stop(self) -> None:
        """Tear down the MCP session and release resources."""
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            self._exit_stack = None
        self._session = None
        if config.MCP_TRANSPORT == "stdio":
            token_proxy.stop()
        global _fake_az_dir
        if _fake_az_dir:
            _fake_az_dir.cleanup()
            _fake_az_dir = None

    async def _connect(self) -> None:
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            if config.MCP_TRANSPORT == "http":
                log.info("Connecting to Azure MCP server via HTTP at %s…", config.MCP_HTTP_URL)
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(config.MCP_HTTP_URL)
                )
            else:
                log.info("Launching Azure MCP container via Docker (stdio)…")
                params = StdioServerParameters(
                    command="docker",
                    args=_build_docker_args(),
                )
                read, write = await stack.enter_async_context(stdio_client(params))

            session = await stack.enter_async_context(ClientSession(read, write))
            log.info("Negotiating MCP protocol…")
            await session.initialize()

            result = await session.list_tools()
            self._tools = result.tools
            self._session = session
            self._exit_stack = stack
            log.info("MCP bridge ready (%s) — %d tools available",
                     config.MCP_TRANSPORT, len(self._tools))
        except Exception:
            await stack.aclose()
            raise

    async def _reconnect(self) -> None:
        log.warning("MCP connection lost — attempting reconnect…")
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            self._exit_stack = None
        self._session = None
        for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
            try:
                await self._connect()
                log.info("Reconnected on attempt %d", attempt)
                return
            except Exception as exc:
                log.error("Reconnect attempt %d failed: %s", attempt, exc)
                if attempt < _RECONNECT_ATTEMPTS:
                    await asyncio.sleep(_RECONNECT_DELAY)
        raise RuntimeError(
            f"Failed to reconnect to Azure MCP server after {_RECONNECT_ATTEMPTS} attempts"
        )

    async def list_tools(self) -> list[Tool]:
        """Return the cached tool list, connecting lazily if needed."""
        if self._session is None:
            try:
                await self._connect()
            except Exception as exc:
                log.warning("list_tools: MCP not connected: %s", exc)
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke an MCP tool. Reconnects automatically on connection failure."""
        async with self._lock:
            for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
                try:
                    if self._session is None:
                        await self._reconnect()
                    result = await self._session.call_tool(name, arguments)
                    return result
                except (BrokenPipeError, ConnectionResetError, EOFError) as exc:
                    log.warning("Tool call failed (attempt %d): %s", attempt, exc)
                    if attempt < _RECONNECT_ATTEMPTS:
                        await self._reconnect()
                    else:
                        raise


# Module-level singleton used by the FastAPI app
bridge = MCPBridge()
