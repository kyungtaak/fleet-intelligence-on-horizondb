targetScope = 'resourceGroup'

param foundryName string

@description('Object ID of the managed identity used by HorizonDB, not its client ID.')
param principalId string

var openAiUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryName
}

resource modelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, principalId, openAiUserRoleId)
  properties: {
    roleDefinitionId: openAiUserRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentId string = modelAccess.id
