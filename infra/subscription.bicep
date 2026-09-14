targetScope = 'subscription'

type DeploymentSettings = {
  resourceGroupName: string
  location: 'westus3'
  namePrefix: string
  administratorLogin: string
  clientIpAddress: string
  clusterCreateMode: 'Create' | 'Update'
  vCores: 2 | 4 | 8 | 16
  replicaCount: int
  zonePlacementPolicy: 'BestEffort' | 'Strict'
}

param settings DeploymentSettings

@secure()
param administratorPassword string

resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: settings.resourceGroupName
  location: settings.location
  tags: {
    application: 'HorizonShip'
    environment: 'dev'
  }
}

module resources './main.bicep' = {
  scope: resourceGroup
  params: {
    location: settings.location
    namePrefix: settings.namePrefix
    administratorLogin: settings.administratorLogin
    administratorPassword: administratorPassword
    clientIpAddress: settings.clientIpAddress
    clusterCreateMode: settings.clusterCreateMode
    vCores: settings.vCores
    replicaCount: settings.replicaCount
    zonePlacementPolicy: settings.zonePlacementPolicy
  }
}

output connection object = resources.outputs.connection
output resourceGroupName string = resourceGroup.name
