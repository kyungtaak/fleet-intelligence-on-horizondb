using './subscription.bicep'

param settings = json(readEnvironmentVariable('HORIZONSHIP_DEPLOYMENT_SETTINGS'))
param administratorPassword = readEnvironmentVariable('HORIZONSHIP_ADMIN_PASSWORD')
