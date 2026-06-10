# Azure MCP Agent

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

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

## Deploying to Azure

The backend runs as a **Container App** with the Azure MCP server as a sidecar container.
The frontend is hosted on **Azure Static Web Apps** (free tier).
A system-assigned **managed identity** on the Container App handles Azure authentication — no service principal needed.

### Option A — GitHub Actions (recommended)

Every push to `main` triggers `.github/workflows/deploy.yml`, which:
1. Deploys Bicep infrastructure (ACR, Container Apps env, SWA).
2. Builds and pushes the Docker image to ACR.
3. Builds the React frontend with the Container App URL baked in.
4. Deploys the frontend to Azure Static Web Apps.
5. Updates the backend CORS policy to allow the SWA origin.

#### One-time setup

Run these commands once to create the OIDC identity GitHub Actions will use.
Replace `OWNER/REPO` with your GitHub repository (e.g. `jsmith/azure-mcp-agent`).

```bash
REPO="OWNER/REPO"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

# 1. Create an app registration for GitHub Actions
APP_ID=$(az ad app create --display-name "github-azure-mcp-agent" --query appId -o tsv)
az ad sp create --id "$APP_ID"

# 2. Federated credential — allows pushes to main to authenticate
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"github-main\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:${REPO}:ref:refs/heads/main\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"

# 3. Federated credential — allows manual (workflow_dispatch) runs
az ad app federated-credential create --id "$APP_ID" --parameters "{
  \"name\": \"github-dispatch\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:${REPO}:ref:refs/heads/main\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"

# 4. Create the resource group and grant the SP Contributor access to it
az group create --name rg-azure-mcp-agent --location eastus
az role assignment create \
  --assignee "$APP_ID" \
  --role Contributor \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/rg-azure-mcp-agent"

# 5. Grant User Access Administrator at subscription scope so the workflow
#    can create role assignments for the Container App managed identity
az role assignment create \
  --assignee "$APP_ID" \
  --role "User Access Administrator" \
  --scope "/subscriptions/$SUBSCRIPTION_ID"
```

Then add these **GitHub repository secrets** (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | `$APP_ID` (the app registration client ID) |
| `AZURE_TENANT_ID` | `$TENANT_ID` |
| `AZURE_SUBSCRIPTION_ID` | `$SUBSCRIPTION_ID` |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

Push to `main` — the workflow runs automatically.

---

### Option B — manual deploy script

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./deploy/deploy.sh [resource-group] [app-name] [location]
# e.g. ./deploy/deploy.sh rg-azure-mcp-agent azuremcpagent eastus
```

Prerequisites: Azure CLI (`az login`), Docker, `jq`.

The script runs in two passes:
1. Deploys infrastructure, builds and pushes the backend image, builds and deploys the frontend.
2. Re-runs the Bicep deployment to add the SWA URL to the backend CORS allow-list.

After deployment the script prints the frontend and backend URLs.

### Architecture in Azure

```
Browser  →  Azure Static Web App (React)
         →  Container App (FastAPI backend)
               └─ Sidecar: azure-mcp (HTTP transport, localhost:5008)
                  └─ Auth: system-assigned managed identity
```

The backend connects to the Azure MCP sidecar via `http://localhost:5008` (HTTP transport) — no Docker socket or token proxy needed. Container Apps injects the managed identity credential endpoint into both containers automatically.

### Role assignments

The deployment assigns **Reader** and **Policy Insights Data Reader** at subscription scope to the managed identity. For write operations (e.g. policy remediation) you will need to add additional roles manually:

```bash
az role assignment create \
  --assignee <identity-principal-id> \
  --role "Resource Policy Contributor" \
  --scope /subscriptions/<subscription-id>
```

The `identityPrincipalId` output from the Bicep deployment gives you the principal ID.

---

## Project structure

```
azure-mcp-agent/
├── .env                        # API keys and Azure config (gitignored)
├── Dockerfile                  # Backend container image
├── deploy/
│   ├── main.bicep              # Infrastructure-as-code (ACR, Container Apps, SWA)
│   ├── main.bicepparam         # Parameter defaults
│   └── deploy.sh               # End-to-end deployment script
├── backend/
│   ├── requirements.txt
│   ├── main.py                 # FastAPI app, routes, lifespan
│   ├── mcp_bridge.py           # MCP session (stdio for local, HTTP for Azure)
│   ├── token_proxy.py          # Local token proxy for az login auth (stdio mode)
│   ├── agent_loop.py           # Claude tool-use loop, SSE event generator
│   ├── tool_filter.py          # Selects relevant tools per request (reduces tokens)
│   ├── models.py               # Pydantic request/response models
│   └── config.py               # Env var loading
└── frontend/
    ├── staticwebapp.config.json  # Azure Static Web Apps routing
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
