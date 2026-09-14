targetScope = 'resourceGroup'

@allowed(['westus3'])
param location string = 'westus3'

@minLength(3)
@maxLength(16)
param namePrefix string = 'horizonship'

@minLength(1)
@maxLength(63)
param administratorLogin string = 'horizonadmin'

@secure()
@minLength(8)
@maxLength(128)
param administratorPassword string

@description('Single public IPv4 address allowed to connect to PostgreSQL. Never use 0.0.0.0.')
param clientIpAddress string

@allowed(['Create', 'Update'])
param clusterCreateMode string = 'Create'

@allowed([2, 4, 8, 16])
param vCores int = 2

@minValue(1)
@maxValue(3)
param replicaCount int = 1

@allowed(['BestEffort', 'Strict'])
param zonePlacementPolicy string = 'BestEffort'

var suffix = uniqueString(resourceGroup().id, namePrefix)
var tags = {
  application: 'HorizonShip'
  environment: 'dev'
  managedBy: 'Bicep'
}

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

resource pool 'Microsoft.HorizonDb/clusters/pools@2026-05-01-preview' existing = {
  parent: cluster
  name: 'DefaultPool'
}

resource clientFirewall 'Microsoft.HorizonDb/clusters/pools/firewallRules@2026-05-01-preview' = {
  parent: pool
  name: 'development-client'
  properties: {
    startIpAddress: clientIpAddress
    endIpAddress: clientIpAddress
    description: 'Single development client IPv4 address'
  }
}

output connection object = {
  clusterName: cluster.name
  databaseHost: cluster.properties.fullyQualifiedDomainName
  databaseName: 'postgres'
  databaseUser: administratorLogin
}
