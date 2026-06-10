#!/usr/bin/env bash
# deploy.sh — end-to-end deployment for Azure MCP Agent
#
# Prerequisites:
#   az login && az account set --subscription <your-subscription>
#   docker
#   node + npm (for frontend build)
#
# Usage:
#   ./deploy/deploy.sh [resource-group] [app-name] [location]
#
# Example:
#   ANTHROPIC_API_KEY=sk-ant-... ./deploy/deploy.sh rg-azure-mcp-agent azuremcpagent eastus

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RG="${1:-rg-azure-mcp-agent}"
APP_NAME="${2:-azuremcpagent}"
LOCATION="${3:-eastus}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set." >&2
  exit 1
fi

echo "=== Step 1: Deploy infrastructure (first pass — no SWA URL yet) ==="
az group create --name "$RG" --location "$LOCATION" --output none

DEPLOY_OUTPUT=$(az deployment group create \
  --resource-group "$RG" \
  --template-file "$REPO_ROOT/deploy/main.bicep" \
  --parameters appName="$APP_NAME" location="$LOCATION" \
               anthropicApiKey="$ANTHROPIC_API_KEY" \
               imageTag="$IMAGE_TAG" \
  --output json)

ACR_SERVER=$(echo "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.acrLoginServer.value')
API_URL=$(echo "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.apiUrl.value')
SWA_HOSTNAME=$(echo "$DEPLOY_OUTPUT" | jq -r '.properties.outputs.swaHostname.value')

echo "  ACR:     $ACR_SERVER"
echo "  API URL: $API_URL"
echo "  SWA:     https://$SWA_HOSTNAME"

echo ""
echo "=== Step 2: Build and push backend Docker image ==="
ACR_NAME="${APP_NAME//[-_]/}acr"   # strip hyphens/underscores to match Bicep var
az acr login --name "$ACR_NAME"

# Ensure the directory exists so the COPY in Dockerfile succeeds.
# When deploying to Azure the frontend goes to SWA, so this can be empty.
mkdir -p "$REPO_ROOT/frontend/dist"

docker build \
  --tag "$ACR_SERVER/azure-mcp-agent:$IMAGE_TAG" \
  --file "$REPO_ROOT/Dockerfile" \
  "$REPO_ROOT"

docker push "$ACR_SERVER/azure-mcp-agent:$IMAGE_TAG"

echo ""
echo "=== Step 3: Build frontend with the Container App URL ==="
npm --prefix "$REPO_ROOT/frontend" install
VITE_API_BASE_URL="$API_URL" npm --prefix "$REPO_ROOT/frontend" run build

echo ""
echo "=== Step 4: Deploy frontend to Static Web App ==="
SWA_NAME="${APP_NAME}-swa"
SWA_TOKEN=$(az staticwebapp secrets list \
  --name "$SWA_NAME" \
  --resource-group "$RG" \
  --query "properties.apiKey" -o tsv)

# Use the SWA CLI if available, otherwise fall back to az staticwebapp upload
if command -v swa &>/dev/null; then
  swa deploy "$REPO_ROOT/frontend/dist" \
    --deployment-token "$SWA_TOKEN" \
    --app-location "$REPO_ROOT/frontend/dist"
else
  az staticwebapp upload \
    --name "$SWA_NAME" \
    --resource-group "$RG" \
    --source "$REPO_ROOT/frontend/dist" \
    --deployment-token "$SWA_TOKEN"
fi

echo ""
echo "=== Step 5: Update backend CORS to allow the SWA origin ==="
SWA_ORIGIN="https://$SWA_HOSTNAME"
az deployment group create \
  --resource-group "$RG" \
  --template-file "$REPO_ROOT/deploy/main.bicep" \
  --parameters appName="$APP_NAME" location="$LOCATION" \
               anthropicApiKey="$ANTHROPIC_API_KEY" \
               imageTag="$IMAGE_TAG" \
               allowedOrigins="$SWA_ORIGIN" \
  --output none

echo ""
echo "=== Deployment complete ==="
echo "  Frontend: https://$SWA_HOSTNAME"
echo "  Backend:  $API_URL"
echo ""
echo "Note: the Container App is scaled to 0 by default — the first request"
echo "after a cold start may take 20-30 seconds while the containers start."
