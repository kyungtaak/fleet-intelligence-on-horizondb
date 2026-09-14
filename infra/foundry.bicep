targetScope = 'resourceGroup'

@allowed(['westus3'])
param location string = 'westus3'

@minLength(3)
@maxLength(16)
param namePrefix string = 'horizonship'

@allowed(['GlobalStandard', 'DataZoneStandard'])
param modelSku string = 'GlobalStandard'

@minValue(1)
param chatCapacity int = 10

@minValue(1)
param embeddingCapacity int = 10

@description('Optional object ID of the backend user, service principal or Managed Identity. Not an application/client ID.')
param modelCallerPrincipalId string = ''

@allowed(['User', 'ServicePrincipal', 'Group'])
param modelCallerPrincipalType string = 'User'

var suffix = uniqueString(resourceGroup().id, namePrefix)

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${namePrefix}-ai-${suffix}'
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  tags: {
    application: 'HorizonShip'
    environment: 'dev'
    managedBy: 'Bicep'
  }
  properties: {
    customSubDomainName: '${namePrefix}-ai-${suffix}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource modelCallerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(modelCallerPrincipalId)) {
  name: guid(foundry.id, modelCallerPrincipalId, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: modelCallerPrincipalId
    principalType: modelCallerPrincipalType
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'gpt-5.4'
  sku: {
    name: modelSku
    capacity: chatCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.4'
      version: '2026-03-05'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'text-embedding-3-small'
  sku: {
    name: modelSku
    capacity: embeddingCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [chat]
}

output connection object = {
  foundryName: foundry.name
  openAiEndpoint: 'https://${foundry.properties.customSubDomainName}.openai.azure.com/'
  chatDeployment: chat.name
  embeddingDeployment: embedding.name
  authentication: 'EntraID'
}