targetScope = 'resourceGroup'

@description('Short workload name used in Azure resource names.')
@minLength(3)
@maxLength(20)
param baseName string = 'swingdesk'

@description('Azure region for every regional resource.')
param location string = resourceGroup().location

@description('Fully qualified container image deployed after the ACR build.')
param image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Create the Container App after its image is available in ACR.')
param deployContainerApp bool = true

@description('Run trading decisions without submitting orders.')
param dryRun bool = true

@secure()
@description('Initial dashboard password. A password hash saved on the mounted share takes precedence after a dashboard password change.')
param dashboardPassword string

@secure()
@description('Stable Flask session-signing secret.')
param dashboardSessionSecret string

@secure()
@description('Coinbase CDP API key name.')
param coinbaseApiKey string

@secure()
@description('Coinbase CDP API private key, including PEM newlines.')
param coinbaseApiSecret string

@description('Resource tags added to each resource.')
param tags object = {
  application: 'swingdesk'
  environment: 'production'
  managedBy: 'bicep'
}

var uniqueSuffix = take(uniqueString(subscription().id, resourceGroup().id, baseName), 8)
var registryName = 'swing${uniqueSuffix}acr'
var storageAccountName = take(toLower(replace('${baseName}${uniqueSuffix}data', '-', '')), 24)
var environmentName = take('${baseName}-${uniqueSuffix}-env-v2', 60)
var containerAppName = take('${baseName}-${uniqueSuffix}-v2', 32)
var identityName = take('${baseName}-${uniqueSuffix}-pull', 128)
var fileShareName = 'swingdesk-data'
var publicIpName = take('${baseName}-${uniqueSuffix}-egress-pip', 80)
var natGatewayName = take('${baseName}-${uniqueSuffix}-nat', 80)
var virtualNetworkName = take('${baseName}-${uniqueSuffix}-vnet', 64)
var infrastructureSubnetName = 'container-apps-infrastructure'

module publicIp 'br/public:avm/res/network/public-ip-address:0.13.0' = {
  params: {
    name: publicIpName
    location: location
    publicIPAddressVersion: 'IPv4'
    publicIPAllocationMethod: 'Static'
    skuName: 'Standard'
    skuTier: 'Regional'
    tags: tags
  }
}

module natGateway 'br/public:avm/res/network/nat-gateway:2.1.1' = {
  params: {
    name: natGatewayName
    location: location
    availabilityZone: -1
    publicIpResourceIds: [
      publicIp.outputs.resourceId
    ]
    tags: tags
  }
}

module virtualNetwork 'br/public:avm/res/network/virtual-network:0.10.2' = {
  params: {
    name: virtualNetworkName
    location: location
    addressPrefixes: [
      '10.20.0.0/22'
    ]
    subnets: [
      {
        name: infrastructureSubnetName
        addressPrefix: '10.20.0.0/23'
        defaultOutboundAccess: false
        delegation: 'Microsoft.App/environments'
        natGatewayResourceId: natGateway.outputs.resourceId
      }
    ]
    tags: tags
  }
}

module identity 'br/public:avm/res/managed-identity/user-assigned-identity:0.6.0' = {
  params: {
    name: identityName
    location: location
    tags: tags
  }
}

module registry 'br/public:avm/res/container-registry/registry:0.13.0' = {
  params: {
    name: registryName
    location: location
    acrAdminUserEnabled: false
    acrSku: 'Basic'
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleSetDefaultAction: 'Allow'
    roleAssignments: [
      {
        principalId: identity.outputs.principalId
        principalType: 'ServicePrincipal'
        roleDefinitionIdOrName: 'AcrPull'
      }
    ]
    tags: tags
  }
}

module storage 'br/public:avm/res/storage/storage-account:0.33.0' = {
  params: {
    name: storageAccountName
    location: location
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: true
    fileServices: {
      shareDeleteRetentionPolicy: {
        enabled: true
        days: 7
      }
      shares: [
        {
          name: fileShareName
          accessTier: 'TransactionOptimized'
          shareQuota: 5
        }
      ]
    }
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
    publicNetworkAccess: 'Enabled'
    requireInfrastructureEncryption: true
    skuName: 'Standard_LRS'
    supportsHttpsTrafficOnly: true
    tags: tags
  }
}

module environment 'br/public:avm/res/app/managed-environment:0.15.0' = {
  params: {
    name: environmentName
    location: location
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    infrastructureSubnetResourceId: virtualNetwork.outputs.subnetResourceIds[0]
    peerTrafficEncryption: true
    publicNetworkAccess: 'Enabled'
    storages: [
      {
        accessMode: 'ReadWrite'
        kind: 'SMB'
        name: fileShareName
        storageAccountName: storage.outputs.name
      }
    ]
    tags: tags
    zoneRedundant: false
  }
}

module app 'br/public:avm/res/app/container-app:0.23.0' = if (deployContainerApp) {
  params: {
    name: containerAppName
    location: location
    environmentResourceId: environment.outputs.resourceId
    containers: [
      {
        name: 'swingdesk'
        image: image
        env: [
          {
            name: 'PORT'
            value: '8080'
          }
          {
            name: 'DRY_RUN'
            value: string(dryRun)
          }
          {
            name: 'BOT_SETTINGS_PATH'
            value: '/data/bot_settings.json'
          }
          {
            name: 'TRADE_STATE_PATH'
            value: '/data/trade_state.json'
          }
          {
            name: 'DASHBOARD_PASSWORD_PATH'
            value: '/data/dashboard_password.json'
          }
          {
            name: 'DASHBOARD_HTTPS_ONLY'
            value: 'true'
          }
          {
            name: 'DASHBOARD_PASSWORD'
            secretRef: 'dashboard-password'
          }
          {
            name: 'DASHBOARD_SESSION_SECRET'
            secretRef: 'dashboard-session-secret'
          }
          {
            name: 'COINBASE_API_KEY'
            secretRef: 'coinbase-api-key'
          }
          {
            name: 'COINBASE_API_SECRET'
            secretRef: 'coinbase-api-secret'
          }
        ]
        probes: [
          {
            type: 'Liveness'
            httpGet: {
              path: '/healthz'
              port: 8080
              scheme: 'HTTP'
            }
            initialDelaySeconds: 10
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          }
          {
            type: 'Readiness'
            httpGet: {
              path: '/healthz'
              port: 8080
              scheme: 'HTTP'
            }
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          }
        ]
        resources: {
          cpu: json('0.25')
          memory: '0.5Gi'
        }
        volumeMounts: [
          {
            mountPath: '/data'
            volumeName: 'data'
          }
        ]
      }
    ]
    ingressAllowInsecure: false
    ingressExternal: true
    ingressTargetPort: 8080
    ingressTransport: 'auto'
    managedIdentities: {
      userAssignedResourceIds: [
        identity.outputs.resourceId
      ]
    }
    registries: [
      {
        server: registry.outputs.loginServer
        identity: identity.outputs.resourceId
      }
    ]
    scaleSettings: {
      minReplicas: 1
      maxReplicas: 1
    }
    secrets: [
      {
        name: 'dashboard-password'
        value: dashboardPassword
      }
      {
        name: 'dashboard-session-secret'
        value: dashboardSessionSecret
      }
      {
        name: 'coinbase-api-key'
        value: coinbaseApiKey
      }
      {
        name: 'coinbase-api-secret'
        value: coinbaseApiSecret
      }
    ]
    volumes: [
      {
        name: 'data'
        storageName: fileShareName
        storageType: 'AzureFile'
      }
    ]
    tags: tags
  }
}

output appName string = app.?outputs.?name ?? ''
output appUrl string = deployContainerApp ? 'https://${app.?outputs.?fqdn}' : ''
output egressIpAddress string = publicIp.outputs.ipAddress
output registryName string = registry.outputs.name
output registryLoginServer string = registry.outputs.loginServer
output storageAccountName string = storage.outputs.name
