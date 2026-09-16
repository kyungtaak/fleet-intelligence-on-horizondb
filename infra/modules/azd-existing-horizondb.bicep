targetScope = 'resourceGroup'

param clusterName string

resource cluster 'Microsoft.HorizonDb/clusters@2026-05-01-preview' existing = {
  name: clusterName
}

output clusterName string = cluster.name
output databaseHost string = cluster.properties.fullyQualifiedDomainName
