// Subscription-scoped module — must be called via module{} from main.bicep.
// Assigns Reader and Policy Insights Data Reader to the Container App's
// managed identity at subscription scope so it can inspect all resource groups.
targetScope = 'subscription'

param principalId string
param containerAppId string

var readerRoleId          = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
var policyInsightsRoleId  = '66bb4e9e-b016-4a94-8249-4c0511c2be84'

resource readerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, containerAppId, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource policyInsightsAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, containerAppId, policyInsightsRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', policyInsightsRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
