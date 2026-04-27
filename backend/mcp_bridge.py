"""
MCPBridge — singleton that owns the docker subprocess running the Azure MCP server
and exposes async list_tools() / call_tool() methods to the rest of the app.
"""
import asyncio
import logging
import os
import tempfile
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

import config
from token_proxy import token_proxy

log = logging.getLogger(__name__)

_RECONNECT_ATTEMPTS = 3
_RECONNECT_DELAY = 2.0  # seconds
_fake_az_dir: tempfile.TemporaryDirectory | None = None


def _build_docker_args() -> list[str]:
    """Build the docker run argument list for the Azure MCP container."""
    args = [
        "run", "--rm", "-i",
        # Never allocate a TTY — it corrupts the JSON-RPC framing
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
    Maintains a single MCP ClientSession backed by a docker subprocess.
    Thread-safe for concurrent async callers via an asyncio.Lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._session: ClientSession | None = None
        self._tools: list[Tool] = []
        self._exit_stack_cm = None  # holds the stdio_client context manager

    async def start(self) -> None:
        """Initialize the MCP session. Call once at server startup."""
        global _fake_az_dir
        if config.AZ_LOGIN_MODE:
            token_proxy.start()
            _fake_az_dir = tempfile.TemporaryDirectory(prefix="azure-mcp-fake-az-")
            fake_az_path = os.path.join(_fake_az_dir.name, "az")
            token_proxy.write_fake_az_script(fake_az_path)
            log.info("Fake az script written to %s", fake_az_path)
        await self._connect()

    async def stop(self) -> None:
        """Tear down the MCP session and docker subprocess."""
        if self._exit_stack_cm is not None:
            try:
                await self._exit_stack_cm.__aexit__(None, None, None)
            except Exception:
                pass
        self._session = None
        self._exit_stack_cm = None
        token_proxy.stop()
        global _fake_az_dir
        if _fake_az_dir:
            _fake_az_dir.cleanup()
            _fake_az_dir = None

    async def _connect(self) -> None:
        params = StdioServerParameters(
            command="docker",
            args=_build_docker_args(),
        )

        log.info("Launching Azure MCP container via docker...")
        cm = stdio_client(params)
        read, write = await cm.__aenter__()
        self._exit_stack_cm = cm

        session = ClientSession(read, write)
        await session.__aenter__()

        log.info("Negotiating MCP protocol...")
        await session.initialize()

        result = await session.list_tools()
        self._tools = result.tools
        self._session = session
        log.info("MCP bridge ready — %d tools available", len(self._tools))

    async def _reconnect(self) -> None:
        log.warning("MCP subprocess lost — attempting reconnect...")
        await self.stop()
        for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
            try:
                await self._connect()
                log.info("Reconnected on attempt %d", attempt)
                return
            except Exception as exc:
                log.error("Reconnect attempt %d failed: %s", attempt, exc)
                if attempt < _RECONNECT_ATTEMPTS:
                    await asyncio.sleep(_RECONNECT_DELAY)
        raise RuntimeError("Failed to reconnect to Azure MCP container after "
                           f"{_RECONNECT_ATTEMPTS} attempts")

    async def list_tools(self) -> list[Tool]:
        """Return the cached tool list."""
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke an MCP tool. Reconnects automatically on subprocess failure."""
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


# Module-level singleton — FastAPI stores this on app.state
bridge = MCPBridge()
