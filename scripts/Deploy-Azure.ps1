[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [string]$Subscription,

    [string]$ResourceGroup = "rg-swingdesk-prod",
    [string]$Location = "eastus2",
    [string]$BaseName = "swingdesk",
    [string]$ImageTag = $(if ($env:GITHUB_SHA) { $env:GITHUB_SHA.Substring(0, [Math]::Min(12, $env:GITHUB_SHA.Length)) } else { "latest" }),
    [switch]$LiveTrading,
    [switch]$SkipBuild,
    [switch]$ValidateOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$requiredSecrets = @(
    "DASHBOARD_PASSWORD",
    "DASHBOARD_SESSION_SECRET",
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET"
)
$root = Split-Path -Parent $PSScriptRoot
$template = Join-Path $root "infra/main.bicep"
$deploymentName = "swingdesk-infra"
$bootstrapImage = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"

function Invoke-AzureCli {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $previousPythonUtf8 = $env:PYTHONUTF8
    $previousPythonIoEncoding = $env:PYTHONIOENCODING
    try {
        $env:PYTHONUTF8 = "1"
        $env:PYTHONIOENCODING = "utf-8"
        $output = & az @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Azure CLI command failed with exit code $LASTEXITCODE."
        }
        return $output
    }
    finally {
        $env:PYTHONUTF8 = $previousPythonUtf8
        $env:PYTHONIOENCODING = $previousPythonIoEncoding
    }
}

function New-DeploymentParametersFile {
    $parameters = @{
        '$schema' = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
        contentVersion = "1.0.0.0"
        parameters = @{
            baseName = @{ value = $BaseName }
            location = @{ value = $Location }
            dryRun = @{ value = -not $LiveTrading }
            dashboardPassword = @{ value = $env:DASHBOARD_PASSWORD }
            dashboardSessionSecret = @{ value = $env:DASHBOARD_SESSION_SECRET }
            coinbaseApiKey = @{ value = $env:COINBASE_API_KEY }
            coinbaseApiSecret = @{ value = $env:COINBASE_API_SECRET }
        }
    }
    $path = Join-Path ([System.IO.Path]::GetTempPath()) "swingdesk-$([guid]::NewGuid().ToString('N')).parameters.json"
    [System.IO.File]::WriteAllText($path, "", [System.Text.UTF8Encoding]::new($false))

    if ($env:OS -eq "Windows_NT") {
        $acl = Get-Acl $path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in @($acl.Access)) {
            $acl.RemoveAccessRuleSpecific($rule)
        }
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        $accessRule = [System.Security.AccessControl.FileSystemAccessRule]::new($identity, "FullControl", "Allow")
        $acl.AddAccessRule($accessRule)
        Set-Acl -Path $path -AclObject $acl
    }
    else {
        & chmod 600 -- $path
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            throw "Unable to restrict the temporary deployment parameters file."
        }
    }

    [System.IO.File]::WriteAllText($path, ($parameters | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
    return $path
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required. Install it, then run 'az login' before this script."
}

Invoke-AzureCli -Arguments @("bicep", "build", "--file", $template, "--stdout") | Out-Null
if ($ValidateOnly) {
    Write-Output "Bicep validation passed. No Azure resources were changed."
    return
}

foreach ($name in $requiredSecrets) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Required environment variable $name is not set."
    }
}

$accountJson = Invoke-AzureCli -Arguments @("account", "show", "--subscription", $Subscription, "--output", "json", "--only-show-errors")
$account = $accountJson | ConvertFrom-Json
if (-not $account.id -or -not $account.tenantId) {
    throw "Unable to resolve the requested Azure subscription and tenant."
}
Invoke-AzureCli -Arguments @("account", "set", "--subscription", $account.id) | Out-Null
$activeAccount = (Invoke-AzureCli -Arguments @("account", "show", "--output", "json", "--only-show-errors")) | ConvertFrom-Json
if ($activeAccount.id -ne $account.id -or $activeAccount.tenantId -ne $account.tenantId) {
    throw "The active Azure tenant or subscription does not match the requested target."
}

Write-Output "Target subscription: $($account.name)"
Write-Output "Target resource group: $ResourceGroup"
Write-Output "Target region: $Location"
Write-Output "Trading mode: $(if ($LiveTrading) { 'LIVE' } else { 'DRY RUN' })"

if (-not $Force -and -not $WhatIfPreference) {
    $confirmation = Read-Host "Type DEPLOY to continue"
    if ($confirmation -cne "DEPLOY") {
        throw "Deployment cancelled."
    }
}

$groupExists = (Invoke-AzureCli -Arguments @("group", "exists", "--name", $ResourceGroup, "--subscription", $account.id, "--output", "tsv", "--only-show-errors")).Trim() -eq "true"
if ($WhatIfPreference -and -not $groupExists) {
    throw "What-if requires the resource group to exist. No resources were changed."
}

if (-not $groupExists) {
    if ($PSCmdlet.ShouldProcess($ResourceGroup, "Create Azure resource group")) {
        Invoke-AzureCli -Arguments @("group", "create", "--name", $ResourceGroup, "--location", $Location, "--subscription", $account.id, "--output", "none", "--only-show-errors") | Out-Null
    }
}

$parametersFile = $null
try {
    $parametersFile = New-DeploymentParametersFile
    $parametersArgument = "@$parametersFile"

    if ($WhatIfPreference) {
        $currentImage = Invoke-AzureCli -Arguments @(
            "containerapp", "list", "--resource-group", $ResourceGroup,
            "--query", "[?tags.application=='swingdesk'].properties.template.containers[0].image | [0]",
            "--output", "tsv", "--only-show-errors"
        )
        if ([string]::IsNullOrWhiteSpace($currentImage)) {
            $currentImage = $bootstrapImage
        }
        Invoke-AzureCli -Arguments @(
            "deployment", "group", "what-if", "--name", $deploymentName,
            "--resource-group", $ResourceGroup, "--template-file", $template,
            "--parameters", $parametersArgument, "image=$currentImage"
        ) | Out-Host
        return
    }

    $registryName = Invoke-AzureCli -Arguments @(
        "acr", "list", "--resource-group", $ResourceGroup,
        "--query", "[?tags.application=='swingdesk'].name | [0]",
        "--output", "tsv", "--only-show-errors"
    )

    if ([string]::IsNullOrWhiteSpace($registryName)) {
        if ($PSCmdlet.ShouldProcess($ResourceGroup, "Bootstrap Swingdesk Azure infrastructure")) {
            $bootstrapJson = Invoke-AzureCli -Arguments @(
                "deployment", "group", "create", "--name", $deploymentName,
                "--resource-group", $ResourceGroup, "--template-file", $template,
                "--parameters", $parametersArgument, "deployContainerApp=false", "--output", "json", "--only-show-errors"
            )
            $bootstrap = $bootstrapJson | ConvertFrom-Json
            $registryName = $bootstrap.properties.outputs.registryName.value
        }
    }

    if (-not $SkipBuild) {
        if ($PSCmdlet.ShouldProcess($registryName, "Build and push Swingdesk image tag $ImageTag")) {
            Invoke-AzureCli -Arguments @(
                "acr", "build", "--registry", $registryName, "--image", "swingdesk:$ImageTag",
                "--file", (Join-Path $root "Dockerfile"), $root, "--output", "none", "--only-show-errors"
            ) | Out-Null
        }
    }

    $finalImage = "$registryName.azurecr.io/swingdesk:$ImageTag"
    if ($PSCmdlet.ShouldProcess($ResourceGroup, "Deploy Swingdesk image $ImageTag")) {
        $deploymentJson = Invoke-AzureCli -Arguments @(
            "deployment", "group", "create", "--name", $deploymentName,
            "--resource-group", $ResourceGroup, "--template-file", $template,
            "--parameters", $parametersArgument, "image=$finalImage", "--output", "json", "--only-show-errors"
        )
        $deployment = $deploymentJson | ConvertFrom-Json
        Write-Output "Swingdesk URL: $($deployment.properties.outputs.appUrl.value)"
        Write-Output "Swingdesk fixed egress IP: $($deployment.properties.outputs.egressIpAddress.value)"
    }
}
finally {
    if ($parametersFile) {
        Remove-Item -LiteralPath $parametersFile -Force -ErrorAction SilentlyContinue
    }
}
