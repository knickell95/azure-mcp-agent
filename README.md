# Azure MCP Agent

A web-based chat interface for the [Microsoft Azure MCP server](https://github.com/Azure/azure-mcp).
Ask natural-language questions about your Azure resources — the agent routes them through Claude to 61 Azure tools covering VMs, storage, policy, Key Vault, AKS, databases, and more.

## Architecture

```
Browser (React)  ←→  FastAPI backend  ←→  Azure MCP container (Docker / stdio)
                                      ←→  Anthropic API (Claude)
                                      ←→  az login token proxy (host)
```

The backend starts a local token proxy server so the Docker container can authenticate using your existing `az login` session — no service principal or secrets required.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | |
| Node.js | 18+ | Only needed to rebuild the frontend |
| Docker | 20.10+ | Pulls `mcr.microsoft.com/azure-sdk/azure-mcp:latest` on first run |
| Azure CLI | Any recent | Must be logged in (`az login`) |
| Anthropic API key | — | [console.anthropic.com](https://console.anthropic.com) |

---

## Setup

### 1. Clone and enter the repo

```bash
git clone <repo-url>
cd azure-mcp-agent
```

### 2. Create the Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 3. Configure environment variables

Copy `.env` and fill in your Anthropic API key:

```bash
cp .env .env.local   # optional — .env is already gitignored
```

Edit `.env`:

```dotenv
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Azure auth — leave blank to use az login (recommended)
# To use a service principal instead, uncomment and fill these:
# AZURE_TENANT_ID=
# AZURE_CLIENT_ID=
# AZURE_CLIENT_SECRET=
# AZURE_SUBSCRIPTION_ID=
```

### 4. Log in to Azure

```bash
az login
az account set --subscription "<your-subscription-name-or-id>"
```

### 5. Pull the Azure MCP Docker image

```bash
docker pull mcr.microsoft.com/azure-sdk/azure-mcp:latest
```

This is done automatically on first run, but pulling ahead of time avoids the ~30 second delay.

---

## Running

### Production mode (single process)

```bash
source .venv/bin/activate
PYTHONPATH=backend uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**.

The backend serves the pre-built React frontend from `frontend/dist/`. If `dist/` doesn't exist yet, build it first:

```bash
cd frontend && npm install && npm run build && cd ..
```

### Development mode (hot reload)

Run the backend and frontend dev server in separate terminals:

```bash
# Terminal 1 — backend with auto-reload
source .venv/bin/activate
PYTHONPATH=backend uvicorn backend.main:app --port 8000 --reload

# Terminal 2 — frontend dev server (proxies /api/* → :8000)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

---

## How authentication works

The Azure MCP container runs as an isolated Docker process with no access to the host filesystem. To authenticate without a service principal:

1. At startup the backend launches a lightweight HTTP server on a random local port.
2. It writes a small `az` wrapper script into a temporary directory and mounts it into the container at `/usr/local/bin/az`.
3. When the container's `AzureCliCredential` calls `az account get-access-token`, the wrapper calls the local proxy server.
4. The proxy fetches a token from the host's `az login` session and returns it to the container in the expected format.

Tokens are cached until 60 seconds before expiry. The proxy and temp files are cleaned up when the server shuts down.

To use a **service principal** instead, set `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_SUBSCRIPTION_ID` in `.env` and leave `AZURE_CLIENT_SECRET` non-empty — the backend detects this automatically and skips the token proxy.

---

## Project structure

```
azure-mcp-agent/
├── .env                        # API keys and Azure config (gitignored)
├── backend/
│   ├── requirements.txt
│   ├── main.py                 # FastAPI app, routes, lifespan
│   ├── mcp_bridge.py           # Manages the Docker subprocess + MCP session
│   ├── token_proxy.py          # Local MSI proxy for az login auth
│   ├── agent_loop.py           # Claude tool-use loop, SSE event generator
│   ├── tool_filter.py          # Selects relevant tools per request (reduces tokens)
│   ├── models.py               # Pydantic request/response models
│   └── config.py               # Env var loading
└── frontend/
    ├── src/
    │   ├── App.tsx             # Root layout (sidebar + chat)
    │   ├── api.ts              # fetch wrappers + SSE stream parser
    │   ├── types.ts            # Shared TypeScript types
    │   ├── store/
    │   │   └── conversation.tsx  # useReducer-based conversation state
    │   └── components/
    │       ├── ChatPanel.tsx     # Input bar + streaming message list
    │       ├── MessageList.tsx   # Scrolling bubble list
    │       ├── MessageBubble.tsx # User / assistant text bubbles
    │       ├── ToolCallCard.tsx  # Collapsible tool invocation display
    │       ├── ToolBrowser.tsx   # Searchable sidebar tool catalogue
    │       └── ToolForm.tsx      # Schema-driven tool execution form
    └── dist/                   # Production build output (gitignored)
```

---

## Troubleshooting

**`Authentication failed` on tool calls**
Run `az login` on the host and retry. If using a service principal, verify all four `AZURE_*` variables are set in `.env`.

**`429 Too Many Requests` from Anthropic**
The backend retries automatically (up to 5 times with backoff). If errors persist, you may be hitting your plan's rate limit — wait a moment before sending another message.

**Docker not found / container fails to start**
Ensure Docker Desktop (or Docker Engine) is running and `docker ps` works without `sudo`. On WSL2, Docker Desktop must have WSL integration enabled for your distro.

**Frontend not loading at `:8000`**
Build the frontend first: `cd frontend && npm run build`. The backend only serves static files if `frontend/dist/` exists.

**`ANTHROPIC_API_KEY is not set`**
Add your key to `.env` at the repo root. The file must be present before starting the backend.
