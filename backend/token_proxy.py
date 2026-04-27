"""
Local MSI token proxy server.

Impersonates the Azure App Service 2019 Managed Identity endpoint so that the
MCP Docker container's DefaultAzureCredential (ManagedIdentityCredential) can
obtain tokens using the host's `az login` session — without needing a service
principal.

The container calls:
  GET http://host.docker.internal:{port}/token?resource={res}&api-version=2019-08-01
  X-IDENTITY-HEADER: {secret}

We proxy that to `az account get-access-token --resource {res}` on the host and
return the token in MSI format. Tokens are cached until 60 seconds before expiry.
"""
import json
import logging
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

# resource URL → {"access_token", "expires_on", "token_type", "resource"}
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def _normalize_resource(resource: str) -> str:
    """Strip .default scope suffix Azure SDKs sometimes append."""
    if resource.endswith("/.default"):
        resource = resource[: -len("/.default")]
    return resource


def _fetch_token(resource: str) -> dict:
    """Get a token from az CLI, with expiry-based caching."""
    resource = _normalize_resource(resource)

    with _cache_lock:
        cached = _cache.get(resource)
        if cached and cached["expires_on"] > time.time() + 60:
            return cached

    log.debug("Fetching token for resource %s via az CLI", resource)
    try:
        proc = subprocess.run(
            ["az", "account", "get-access-token", "--resource", resource, "--output", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"az account get-access-token failed: {exc.stderr.strip()}"
        ) from exc

    data = json.loads(proc.stdout)

    # Parse "2026-04-05 23:18:49.000000" → Unix timestamp
    raw_expiry = data.get("expiresOn", "")
    try:
        from datetime import datetime
        dt = datetime.strptime(raw_expiry, "%Y-%m-%d %H:%M:%S.%f")
        expires_on = int(dt.timestamp())
    except ValueError:
        expires_on = int(time.time()) + 3600  # fallback: 1 hour

    entry = {
        "access_token": data["accessToken"],
        "expires_on": str(expires_on),
        "token_type": "Bearer",
        "resource": resource,
    }
    with _cache_lock:
        _cache[resource] = {**entry, "expires_on": expires_on}  # store int for comparison

    return entry


class _Handler(BaseHTTPRequestHandler):
    _secret: str = ""

    def log_message(self, fmt, *args):  # suppress default access log
        log.debug("TokenProxy: " + fmt, *args)

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)
        resource = params.get("resource", ["https://management.azure.com/"])[0]

        if path == "/az-token":
            # Az CLI format — called by our fake az script inside the container.
            # No auth header needed; the script is only accessible from inside the container.
            self._handle_az_token(resource)
        elif path == "/token":
            # MSI App Service 2019 format — guarded by identity header
            if self.headers.get("X-IDENTITY-HEADER") != self._secret:
                self._send_json(401, {"error": "unauthorized"})
                return
            self._handle_msi_token(resource)
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_msi_token(self, resource: str) -> None:
        try:
            token = _fetch_token(resource)
            self._send_json(200, {
                "access_token": token["access_token"],
                "expires_on": token["expires_on"],
                "token_type": token["token_type"],
                "resource": resource,
            })
        except Exception as exc:
            log.error("MSI token request failed for %s: %s", resource, exc)
            self._send_json(500, {"error": str(exc)})

    def _handle_az_token(self, resource: str) -> None:
        """Return token in az CLI format: {accessToken, expiresOn, tokenType, ...}"""
        try:
            token = _fetch_token(resource)
            # AzureCliCredential expects expiresOn as a datetime string
            from datetime import datetime
            expires_dt = datetime.fromtimestamp(int(token["expires_on"])).strftime(
                "%Y-%m-%d %H:%M:%S.%f"
            )
            self._send_json(200, {
                "accessToken": token["access_token"],
                "expiresOn": expires_dt,
                "tokenType": "Bearer",
                "subscription": "",
                "tenant": "",
            })
        except Exception as exc:
            log.error("Az token request failed for %s: %s", resource, exc)
            self._send_json(500, {"error": str(exc)})


class TokenProxyServer:
    """Starts a background-thread HTTP server that serves MSI token requests."""

    def __init__(self) -> None:
        self.port: int = 0
        self.secret: str = ""
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Bind to a random port and start serving. Sets self.port and self.secret."""
        self.secret = secrets.token_hex(16)

        # Bind on all interfaces so Docker containers can reach us
        self._server = HTTPServer(("0.0.0.0", 0), _Handler)
        self.port = self._server.server_address[1]

        _Handler._secret = self.secret

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="token-proxy",
            daemon=True,
        )
        self._thread.start()
        log.info("MSI token proxy listening on port %d", self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    @property
    def identity_endpoint(self) -> str:
        """IDENTITY_ENDPOINT value to pass into the Docker container."""
        return f"http://host.docker.internal:{self.port}/token"

    @property
    def az_token_endpoint(self) -> str:
        """Endpoint returning tokens in az CLI JSON format for the fake az script."""
        return f"http://host.docker.internal:{self.port}/az-token"

    def write_fake_az_script(self, path: str) -> None:
        """
        Write a POSIX sh script that impersonates `az account get-access-token`.
        AzureCliCredential inside the container will call this instead of the real az.
        """
        script = f"""\
#!/bin/sh
# Fake az CLI — proxies to the token proxy on the host (az login mode)
# Written by azure-mcp-agent at startup; safe to delete after server stops.

case "$*" in
  *"account get-access-token"*)
    RESOURCE="https://management.azure.com/"
    set -- "$@"
    while [ "$#" -gt 0 ]; do
      [ "$1" = "--resource" ] && {{ RESOURCE="$2"; break; }}
      shift
    done
    wget -q -O - "{self.az_token_endpoint}?resource=${{RESOURCE}}" 2>/dev/null && exit 0
    echo '{{"error":"token_proxy_unreachable"}}' >&2
    exit 1
    ;;
  *)
    exit 0
    ;;
esac
"""
        import os
        with open(path, "w") as f:
            f.write(script)
        os.chmod(path, 0o755)


token_proxy = TokenProxyServer()
