targetScope = 'resourceGroup'

param clusterName string
param ruleName string

resource cluster 'Microsoft.HorizonDb/clusters@2026-05-01-preview' existing = {
  name: clusterName
}

resource pool 'Microsoft.HorizonDb/clusters/pools@2026-05-01-preview' existing = {
  parent: cluster
  name: 'DefaultPool'
}

resource firewallRule 'Microsoft.HorizonDb/clusters/pools/firewallRules@2026-05-01-preview' = {
  parent: pool
  name: ruleName
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
    description: 'Temporary Azure service access for HorizonShip Container Apps'
  }
}

output ruleId string = firewallRule.id