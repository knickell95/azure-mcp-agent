// Azure MCP Agent — infrastructure
//
// Deploys:
//   - Azure Container Registry (ACR) for the backend image
//   - Log Analytics workspace + Container Apps environment
//   - Container App: FastAPI backend (main) + azure-mcp (sidecar, HTTP transport)
//   - System-assigned managed identity with Reader + Policy Insights roles
//   - Azure Static Web App for the React frontend
//
// Usage: see deploy.sh

targetScope = 'resourceGroup'

// ── Parameters ────────────────────────────────────────────────────────────────

@description('Short name prefix used for all resources.')
param appName string = 'azuremcpagent'

@description('Azure region for Container Apps and supporting resources.')
param location string = resourceGroup().location

// Static Web Apps is only available in a handful of regions; use the closest.
// https://learn.microsoft.com/azure/static-web-apps/quotas
@description('Region for the Static Web App (must support SWA).')
param swaLocation string = 'eastus2'

@description('Anthropic API key stored as a Container App secret.')
@secure()
param anthropicApiKey string

@description('Comma-separated extra CORS origins (e.g. the SWA URL after first deploy).')
param allowedOrigins string = ''

@description('Tag for the backend container image in ACR.')
param imageTag string = 'latest'

// ── Variables ─────────────────────────────────────────────────────────────────

var acrName = '${replace(appName, '-', '')}acr'
var logName = '${appName}-logs'
var envName = '${appName}-env'
var appContainerName = '${appName}-api'
var swaName = '${appName}-swa'

// The sidecar listens on this port in HTTP transport mode.
var mcpSidecarPort = '5008'

// Reader role — lets the MI inspect all subscription resources.
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
// Policy Insights Data Reader — lets the MI read policy compliance data.
var policyInsightsRoleId = '66bb4e9e-b016-4a94-8249-4c0511c2be84'

// ── Container Registry ────────────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

// ── Log Analytics ─────────────────────────────────────────────────────────────

resource logs 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── Container Apps environment ────────────────────────────────────────────────

resource env 'Microsoft.App/managedEnvironments@2023-11-02-preview' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// ── Container App ─────────────────────────────────────────────────────────────

// Build the ALLOWED_ORIGINS value: always include localhost dev origins;
// append the caller-supplied origins (typically the SWA URL).
var corsOrigins = empty(allowedOrigins)
  ? 'http://localhost:5173,http://127.0.0.1:5173'
  : 'http://localhost:5173,http://127.0.0.1:5173,${allowedOrigins}'

resource containerApp 'Microsoft.App/containerApps@2023-11-02-preview' = {
  name: appContainerName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    environmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'anthropic-api-key'
          value: anthropicApiKey
        }
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      scale: { minReplicas: 0, maxReplicas: 1 }
      containers: [
        // ── Main container: FastAPI backend ─────────────────────────────────
        {
          name: 'backend'
          image: '${acr.properties.loginServer}/azure-mcp-agent:${imageTag}'
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'ANTHROPIC_API_KEY', secretRef: 'anthropic-api-key' }
            { name: 'MCP_TRANSPORT', value: 'http' }
            { name: 'MCP_HTTP_URL', value: 'http://localhost:${mcpSidecarPort}' }
            { name: 'ALLOWED_ORIGINS', value: corsOrigins }
          ]
        }
        // ── Sidecar: Azure MCP server in HTTP transport mode ────────────────
        // The sidecar shares localhost with the main container, so the backend
        // can reach it at http://localhost:5008 without any network config.
        // Authentication uses the Container App's system-assigned managed
        // identity — no service principal or az login needed.
        {
          name: 'azure-mcp'
          image: 'mcr.microsoft.com/azure-sdk/azure-mcp:latest'
          // Switch from the default stdio transport to HTTP so the backend
          // can connect over TCP rather than stdin/stdout.
          args: [ 'server', 'start', '--transport', 'http', '--port', mcpSidecarPort ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            // Pass the subscription ID so the MCP server targets the right scope.
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
          ]
        }
      ]
    }
  }
}

// ── Role assignments for the managed identity ─────────────────────────────────
// Assign roles at subscription scope so the MI can read resources across all
// resource groups.  Add Contributor or more specific roles if you need write
// operations (e.g. policy remediation requires Resource Policy Contributor).

resource readerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, containerApp.id, readerRoleId)
  scope: subscription()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource policyInsightsAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, containerApp.id, policyInsightsRoleId)
  scope: subscription()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', policyInsightsRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Static Web App ────────────────────────────────────────────────────────────

resource swa 'Microsoft.Web/staticSites@2023-01-01' = {
  name: swaName
  location: swaLocation
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

// ── Outputs ───────────────────────────────────────────────────────────────────

@description('HTTPS URL of the Container App API backend.')
output apiUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'

@description('ACR login server (e.g. myacr.azurecr.io).')
output acrLoginServer string = acr.properties.loginServer

@description('Default hostname of the Static Web App.')
output swaHostname string = swa.properties.defaultHostname

@description('Principal ID of the Container App managed identity (for manual role assignments).')
output identityPrincipalId string = containerApp.identity.principalId
