targetScope = 'resourceGroup'

@minLength(1)
@maxLength(50)
@description('Azure Developer CLI environment name')
param environmentName string

@allowed(['westus3'])
@metadata({
  azd: {
    type: 'location'
  }
})
param location string = 'westus3'

@minLength(3)
@maxLength(16)
param namePrefix string = 'horizonship'

@allowed(['create', 'existing'])
param horizonDbMode string = 'existing'

@allowed(['Create', 'Update'])
param horizonDbCreateMode string = 'Create'

param existingHorizonDbResourceGroup string = ''
param existingHorizonDbClusterName string = ''

@minLength(1)
@maxLength(63)
param administratorLogin string = 'horizonadmin'

@secure()
@minLength(8)
@maxLength(128)
param administratorPassword string

param databaseName string = 'postgres'

@minLength(1)
param openAiEndpoint string

@secure()
@minLength(1)
param openAiKey string

param chatDeployment string = 'gpt-5.4'
param embeddingDeployment string = 'text-embedding-3-small'

@allowed(['azure_openai', 'horizondb'])
param chatProvider string = 'azure_openai'

@allowed(['azure_openai', 'horizondb'])
param embeddingProvider string = 'azure_openai'

param runDatabaseSetup bool = false
param allowAzureServicesToHorizonDb bool = true
param captureQueryPlan bool = true

@allowed([2, 4, 8, 16])
param horizonDbVCores int = 2

@minValue(1)
@maxValue(3)
param horizonDbReplicaCount int = 1

@allowed(['BestEffort', 'Strict'])
param horizonDbZonePlacementPolicy string = 'BestEffort'

var resourceToken = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName, location))
var compactEnvironmentName = take(replace(toLower(environmentName), '-', ''), 12)
var prefix = 'hs-${compactEnvironmentName}-${take(resourceToken, 6)}'
var containerEnvironmentName = take('${prefix}-cae', 32)
var registryName = 'hs${take(resourceToken, 22)}'
var backendName = take('${prefix}-api', 32)
var frontendName = take('${prefix}-web', 32)
var backendIdentityName = take('${prefix}-api-id', 128)
var frontendIdentityName = take('${prefix}-web-id', 128)
var tags = {
  'azd-env-name': environmentName
  application: 'HorizonShip'
  environment: 'demo'
  managedBy: 'azd'
}

module createdHorizonDb './modules/azd-horizondb.bicep' = if (horizonDbMode == 'create') {
  params: {
    location: location
    namePrefix: namePrefix
    administratorLogin: administratorLogin
    administratorPassword: administratorPassword
    clusterCreateMode: horizonDbCreateMode
    vCores: horizonDbVCores
    replicaCount: horizonDbReplicaCount
    zonePlacementPolicy: horizonDbZonePlacementPolicy
    tags: tags
  }
}

module existingHorizonDb './modules/azd-existing-horizondb.bicep' = if (horizonDbMode == 'existing') {
  scope: resourceGroup(existingHorizonDbResourceGroup)
  params: {
    clusterName: existingHorizonDbClusterName
  }
}

var databaseResourceGroupName = horizonDbMode == 'create'
  ? resourceGroup().name
  : existingHorizonDbResourceGroup
var databaseClusterName = createdHorizonDb.?outputs.?clusterName ?? existingHorizonDb.?outputs.?clusterName ?? ''
var databaseHost = createdHorizonDb.?outputs.?databaseHost ?? existingHorizonDb.?outputs.?databaseHost ?? ''
var parameterGroupId = createdHorizonDb.?outputs.?parameterGroupId ?? ''
var firewallRuleName = take('${prefix}-azure-services', 63)

module horizonDbFirewall './modules/azd-horizondb-firewall.bicep' = if (allowAzureServicesToHorizonDb) {
  scope: resourceGroup(databaseResourceGroupName)
  params: {
    clusterName: databaseClusterName
    ruleName: firewallRuleName
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: containerEnvironmentName
  location: location
  tags: tags
  properties: {}
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource backendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: backendIdentityName
  location: location
  tags: tags
}

resource frontendIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: frontendIdentityName
  location: location
  tags: tags
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource backendAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, backendIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: backendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource frontendAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, frontendIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: frontendIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

var backendHost = backend.properties.configuration.ingress.fqdn
var backendUri = 'https://${backendHost}'
var frontendHost = '${frontendName}.${containerEnvironment.properties.defaultDomain}'
var frontendUri = 'https://${frontendHost}'
var placeholderImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var shouldRunDatabaseSetup = (horizonDbMode == 'create' && horizonDbCreateMode == 'Create') || runDatabaseSetup

resource backend 'Microsoft.App/containerApps@2025-01-01' = {
  name: backendName
  location: location
  tags: union(tags, {
    'azd-service-name': 'backend'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${backendIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        allowInsecure: false
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: backendIdentity.id
        }
      ]
      secrets: [
        {
          name: 'database-password'
          value: administratorPassword
        }
        {
          name: 'openai-key'
          value: openAiKey
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: placeholderImage
          env: [
            {
              name: 'HOST'
              value: '0.0.0.0'
            }
            {
              name: 'PORT'
              value: '8000'
            }
            {
              name: 'RUN_DATABASE_SETUP'
              value: shouldRunDatabaseSetup ? 'true' : 'false'
            }
            {
              name: 'AZURE_PG_HOST'
              value: databaseHost
            }
            {
              name: 'AZURE_PG_NAME'
              value: databaseName
            }
            {
              name: 'AZURE_PG_USER'
              value: administratorLogin
            }
            {
              name: 'AZURE_PG_PASSWORD'
              secretRef: 'database-password'
            }
            {
              name: 'AZURE_PG_PORT'
              value: '5432'
            }
            {
              name: 'AZURE_PG_SSLMODE'
              value: 'require'
            }
            {
              name: 'AZURE_OPENAI_ENDPOINT'
              value: openAiEndpoint
            }
            {
              name: 'AZURE_OPENAI_KEY'
              secretRef: 'openai-key'
            }
            {
              name: 'AZURE_OPENAI_DEPLOYMENT'
              value: chatDeployment
            }
            {
              name: 'AZURE_EMBED_DEPLOYMENT'
              value: embeddingDeployment
            }
            {
              name: 'CHAT_PROVIDER'
              value: chatProvider
            }
            {
              name: 'EMBEDDING_PROVIDER'
              value: embeddingProvider
            }
            {
              name: 'EMBEDDING_MODEL_ALIAS'
              value: 'horizonship-embedding'
            }
            {
              name: 'CHAT_MODEL_ALIAS'
              value: 'horizonship-chat'
            }
            {
              name: 'CAPTURE_QUERY_PLAN'
              value: captureQueryPlan ? 'true' : 'false'
            }
            {
              name: 'CORS_ORIGINS'
              value: '["${frontendUri}"]'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [backendAcrPull, horizonDbFirewall]
}

resource frontend 'Microsoft.App/containerApps@2025-01-01' = {
  name: frontendName
  location: location
  tags: union(tags, {
    'azd-service-name': 'frontend'
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${frontendIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 80
        transport: 'auto'
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: frontendIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'frontend'
          image: placeholderImage
          env: [
            {
              name: 'BACKEND_HOST'
              value: backendHost
            }
            {
              name: 'NGINX_ENVSUBST_FILTER'
              value: '^BACKEND_HOST$'
            }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [frontendAcrPull]
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = resourceGroup().name
output AZURE_CONTAINER_ENVIRONMENT_NAME string = containerEnvironment.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = registry.name
output HORIZONDB_MODE string = horizonDbMode
output HORIZONDB_CREATE_MODE string = horizonDbMode == 'create' ? 'Update' : horizonDbCreateMode
output RUN_DATABASE_SETUP string = shouldRunDatabaseSetup ? 'true' : 'false'
output HORIZONDB_RESOURCE_GROUP string = databaseResourceGroupName
output HORIZONDB_CLUSTER_NAME string = databaseClusterName
output HORIZONDB_PARAMETER_GROUP_ID string = parameterGroupId
output HORIZONDB_FIREWALL_RULE_ID string = horizonDbFirewall.?outputs.?ruleId ?? ''
output AZURE_PG_HOST string = databaseHost
output SERVICE_BACKEND_NAME string = backend.name
output SERVICE_BACKEND_URI string = backendUri
output SERVICE_BACKEND_IMAGE_NAME string = backend.properties.template.containers[0].image
output SERVICE_FRONTEND_NAME string = frontend.name
output SERVICE_FRONTEND_URI string = frontendUri
output SERVICE_FRONTEND_IMAGE_NAME string = frontend.properties.template.containers[0].image