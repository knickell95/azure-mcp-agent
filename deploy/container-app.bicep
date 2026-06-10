// Container App: FastAPI backend (main) + azure-mcp sidecar (HTTP transport).
// Deploy this AFTER the backend image has been pushed to ACR.
// Requires infra.bicep to have been deployed first.

targetScope = 'resourceGroup'

@description('Short name prefix — must match the value used in infra.bicep.')
@minLength(2)
param appName string = 'azuremcpagent'

@description('Azure region — must match the value used in infra.bicep.')
param location string = resourceGroup().location

@description('Tag of the backend image that already exists in ACR.')
param imageTag string

@description('Anthropic API key stored as a Container App secret.')
@secure()
param anthropicApiKey string

@description('Comma-separated extra CORS origins (e.g. the SWA URL).')
param allowedOrigins string = ''

// ── Derived names (must align with infra.bicep) ───────────────────────────────

var acrName          = '${replace(appName, '-', '')}acr'
var envName          = '${appName}-env'
var appContainerName = '${appName}-api'
// Default HTTP port used by azmcp server start --transport http.
// Must match MCP_HTTP_URL in the backend container's env.
var mcpSidecarPort   = '5000'

// ── References to resources created by infra.bicep ───────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  #disable-next-line BCP334
  name: acrName
}

resource env 'Microsoft.App/managedEnvironments@2023-11-02-preview' existing = {
  name: envName
}

// ── Container App ─────────────────────────────────────────────────────────────

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
        { name: 'anthropic-api-key', value: anthropicApiKey }
        { name: 'acr-password',      value: acr.listCredentials().passwords[0].value }
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
            { name: 'MCP_TRANSPORT',     value: 'http' }
            { name: 'MCP_HTTP_URL',      value: 'http://localhost:${mcpSidecarPort}' }
            { name: 'ALLOWED_ORIGINS',   value: corsOrigins }
          ]
        }
        // ── Sidecar: Azure MCP server in HTTP transport mode ────────────────
        // Shares localhost with the main container; authenticates via the
        // Container App's system-assigned managed identity automatically.
        {
          name: 'azure-mcp'
          image: 'mcr.microsoft.com/azure-sdk/azure-mcp:latest'
          // No --outgoing-auth-strategy needed: the default DefaultAzureCredential chain
          // automatically picks up the Container App's system-assigned managed identity
          // via the IDENTITY_ENDPOINT/IDENTITY_HEADER endpoints set by the platform.
          // --dangerously-disable-http-incoming-auth: safe because the sidecar is only
          //   reachable over localhost within the same Container App replica.
          args: [ '--transport', 'http', '--dangerously-disable-http-incoming-auth' ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AZURE_SUBSCRIPTION_ID',                    value: subscription().subscriptionId }
            { name: 'AZURE_MCP_INCLUDE_PRODUCTION_CREDENTIALS', value: 'true' }
          ]
        }
      ]
    }
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────

@description('HTTPS URL of the Container App API backend.')
output apiUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'

@description('Principal ID of the Container App managed identity.')
output identityPrincipalId string = containerApp.identity.principalId
