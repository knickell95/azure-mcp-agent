// Stable infrastructure: ACR, Log Analytics, Container Apps environment, SWA.
// Deploy this first; push the Docker image; then deploy container-app.bicep.

targetScope = 'resourceGroup'

@description('Short name prefix used for all resources.')
@minLength(2)
param appName string = 'azuremcpagent'

@description('Azure region for Container Apps and supporting resources.')
param location string = resourceGroup().location

// Static Web Apps is only available in a handful of regions.
// https://learn.microsoft.com/azure/static-web-apps/quotas
@description('Region for the Static Web App.')
param swaLocation string = 'westus2'

var acrName = '${replace(appName, '-', '')}acr'
var logName = '${appName}-logs'
var envName = '${appName}-env'
var swaName  = '${appName}-swa'

// ── Container Registry ────────────────────────────────────────────────────────

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  #disable-next-line BCP334
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

// ── Static Web App ────────────────────────────────────────────────────────────

resource swa 'Microsoft.Web/staticSites@2023-01-01' = {
  name: swaName
  location: swaLocation
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

// ── Outputs ───────────────────────────────────────────────────────────────────

@description('ACR login server (e.g. myacr.azurecr.io).')
output acrLoginServer string = acr.properties.loginServer

@description('Default hostname of the Static Web App.')
output swaHostname string = swa.properties.defaultHostname
