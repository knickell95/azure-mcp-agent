using './main.bicep'

// Required — set before deploying.
// Pass via CLI to avoid storing the key in source control:
//   az deployment group create ... --parameters anthropicApiKey=$ANTHROPIC_API_KEY
param anthropicApiKey = ''

// Optional overrides
param appName = 'azuremcpagent'
param location = 'westus2'
param swaLocation = 'westus2'
param imageTag = 'latest'

// After the first deploy, copy the SWA hostname from the output and set it here,
// then redeploy so the backend CORS policy allows the SWA origin.
// Example: param allowedOrigins = 'https://wonderful-desert-123.azurestaticapps.net'
param allowedOrigins = ''
