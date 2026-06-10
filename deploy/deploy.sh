#!/usr/bin/env bash
# deploy.sh — end-to-end deployment for Azure MCP Agent
#
# Prerequisites:
#   az login && az account set --subscription <your-subscription>
#   docker, node + npm, jq
#
# Usage:
#   ./deploy/deploy.sh [resource-group] [app-name] [location]
#
# Example:
#   ANTHROPIC_API_KEY=sk-ant-... ./deploy/deploy.sh rg-azure-mcp-agent azuremcpagent westus2

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RG="${1:-rg-azure-mcp-agent}"
APP_NAME="${2:-azuremcpagent}"
LOCATION="${3:-westus2}"
IMAGE_TAG="${IMAGE_TAG:-$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo latest)}"
ACR_NAME="${APP_NAME//[-_]/}acr"
SWA_NAME="${APP_NAME}-swa"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ERROR: ANTHROPIC_API_KEY is not set." >&2
  exit 1
fi

echo "=== Step 1: Deploy stable infrastructure (ACR, env, SWA) ==="
az group create --name "$RG" --location "$LOCATION" --output none

INFRA_OUTPUT=$(az deployment group create \
  --resource-group "$RG" \
  --template-file "$REPO_ROOT/deploy/infra.bicep" \
  --parameters appName="$APP_NAME" location="$LOCATION" \
  --output json)

ACR_SERVER=$(echo "$INFRA_OUTPUT" | jq -r '.properties.outputs.acrLoginServer.value')
SWA_HOSTNAME=$(echo "$INFRA_OUTPUT" | jq -r '.properties.outputs.swaHostname.value')

echo "  ACR: $ACR_SERVER"
echo "  SWA: https://$SWA_HOSTNAME"

echo ""
echo "=== Step 2: Build and push backend Docker image (tag: $IMAGE_TAG) ==="
az acr login --name "$ACR_NAME"
mkdir -p "$REPO_ROOT/frontend/dist"   # empty placeholder; frontend goes to SWA

docker build \
  --tag "$ACR_SERVER/azure-mcp-agent:$IMAGE_TAG" \
  --file "$REPO_ROOT/Dockerfile" \
  "$REPO_ROOT"

docker push "$ACR_SERVER/azure-mcp-agent:$IMAGE_TAG"

echo ""
echo "=== Step 3: Deploy Container App (image now exists in ACR) ==="
APP_OUTPUT=$(az deployment group create \
  --resource-group "$RG" \
  --template-file "$REPO_ROOT/deploy/container-app.bicep" \
  --parameters appName="$APP_NAME" location="$LOCATION" \
               imageTag="$IMAGE_TAG" \
               anthropicApiKey="$ANTHROPIC_API_KEY" \
  --output json)

API_URL=$(echo "$APP_OUTPUT" | jq -r '.properties.outputs.apiUrl.value')
PRINCIPAL_ID=$(echo "$APP_OUTPUT" | jq -r '.properties.outputs.identityPrincipalId.value')

echo "  API URL: $API_URL"

echo ""
echo "=== Step 4: Assign roles to managed identity ==="
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
SCOPE="/subscriptions/$SUBSCRIPTION_ID"

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Reader" \
  --scope "$SCOPE" \
  --output none || true

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "66bb4e9e-b016-4a94-8249-4c0511c2be84" \
  --scope "$SCOPE" \
  --output none || true

echo ""
echo "=== Step 5: Build frontend ==="
npm --prefix "$REPO_ROOT/frontend" install
VITE_API_BASE_URL="$API_URL" npm --prefix "$REPO_ROOT/frontend" run build

echo ""
echo "=== Step 6: Deploy frontend to Static Web App ==="
SWA_TOKEN=$(az staticwebapp secrets list \
  --name "$SWA_NAME" \
  --resource-group "$RG" \
  --query "properties.apiKey" -o tsv)

npx --yes @azure/static-web-apps-cli@latest deploy "$REPO_ROOT/frontend/dist" \
  --deployment-token "$SWA_TOKEN" \
  --env production

echo ""
echo "=== Step 7: Update backend CORS with SWA origin ==="
az deployment group create \
  --resource-group "$RG" \
  --template-file "$REPO_ROOT/deploy/container-app.bicep" \
  --parameters appName="$APP_NAME" location="$LOCATION" \
               imageTag="$IMAGE_TAG" \
               anthropicApiKey="$ANTHROPIC_API_KEY" \
               allowedOrigins="https://$SWA_HOSTNAME" \
  --output none

echo ""
echo "=== Deployment complete ==="
echo "  Frontend: https://$SWA_HOSTNAME"
echo "  Backend:  $API_URL"
echo ""
echo "Note: the Container App scales to 0 — the first request after inactivity"
echo "may take 20-30 seconds while the containers start."
