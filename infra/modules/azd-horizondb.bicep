targetScope = 'resourceGroup'

@allowed(['westus3'])
param location string

@minLength(3)
@maxLength(16)
param namePrefix string

@minLength(1)
@maxLength(63)
param administratorLogin string

@secure()
@minLength(8)
@maxLength(128)
param administratorPassword string

@allowed(['Create', 'Update'])
param clusterCreateMode string = 'Create'

@allowed([2, 4, 8, 16])
param vCores int = 2

@minValue(1)
@maxValue(3)
param replicaCount int = 1

@allowed(['BestEffort', 'Strict'])
param zonePlacementPolicy string = 'BestEffort'

param tags object

var suffix = uniqueString(resourceGroup().id, namePrefix)

resource parameterGroup 'Microsoft.HorizonDb/parameterGroups@2026-05-01-preview' = {
  name: '${namePrefix}-params-${suffix}'
  location: location
  tags: tags
  properties: {
    pgVersion: 17
    description: 'Extensions required by HorizonShip'
    applyImmediately: true
    parameters: [
      {
        name: 'azure.extensions'
        value: 'azure_ai,vector,pg_diskann,postgis,uuid-ossp'
      }
    ]
  }
}

resource cluster 'Microsoft.HorizonDb/clusters@2026-05-01-preview' = {
  name: '${namePrefix}-db-${suffix}'
  location: location
  tags: tags
  properties: {
    createMode: clusterCreateMode
    version: '17'
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    vCores: vCores
    replicaCount: replicaCount
    zonePlacementPolicy: zonePlacementPolicy
    authConfig: {
      passwordAuth: 'Enabled'
      entraIdAuth: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
    parameterGroup: {
      id: parameterGroup.id
      applyImmediately: true
    }
  }
}

output clusterName string = cluster.name
output databaseHost string = cluster.properties.fullyQualifiedDomainName
output parameterGroupId string = parameterGroup.id
