targetScope = 'subscription'

type DeploymentSettings = {
  resourceGroupName: string
  location: 'westus3'
  namePrefix: string
  modelSku: 'GlobalStandard' | 'DataZoneStandard'
  chatCapacity: int
  embeddingCapacity: int
  modelCallerPrincipalId: string
  modelCallerPrincipalType: 'User' | 'ServicePrincipal' | 'Group'
}

param settings DeploymentSettings

resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: settings.resourceGroupName
  location: settings.location
  tags: {
    application: 'HorizonShip'
    environment: 'dev'
  }
}

module resources './foundry.bicep' = {
  scope: resourceGroup
  params: {
    location: settings.location
    namePrefix: settings.namePrefix
    modelSku: settings.modelSku
    chatCapacity: settings.chatCapacity
    embeddingCapacity: settings.embeddingCapacity
    modelCallerPrincipalId: settings.modelCallerPrincipalId
    modelCallerPrincipalType: settings.modelCallerPrincipalType
  }
}

output connection object = resources.outputs.connection
output resourceGroupName string = resourceGroup.name