targetScope = 'resourceGroup'

@description('Name of the existing Foundry AIServices account with project management enabled.')
param foundryName string

@description('Must match the location of the existing Foundry account.')
param location string = 'westus3'

@minLength(2)
@maxLength(64)
param projectName string = 'horizonship'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: {
    application: 'HorizonShip'
    environment: 'dev'
    managedBy: 'Bicep'
  }
  properties: {
    displayName: 'HorizonShip'
    description: 'Project for exploring the existing HorizonShip model deployments in Foundry.'
  }
}

output projectId string = project.id
