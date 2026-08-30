param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Waitress = Join-Path $ProjectRoot ".venv\Scripts\waitress-serve.exe"
$PasswordHash = Join-Path $ProjectRoot "dashboard_password.json"
$SecretPath = Join-Path $ProjectRoot "dashboard_service_secret.txt"
$LogDirectory = Join-Path $ProjectRoot "logs"
$LogPath = Join-Path $LogDirectory "dashboard-service.log"

if (-not (Test-Path $Waitress)) {
    throw "Dashboard dependencies are not installed at $Waitress."
}
if (-not (Test-Path $PasswordHash)) {
    throw "Dashboard password is not configured. Run configure_dashboard_password.py first."
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
if (-not (Test-Path $SecretPath)) {
    $randomSecret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
    ConvertTo-SecureString $randomSecret -AsPlainText -Force |
        ConvertFrom-SecureString |
        Set-Content -Path $SecretPath -Encoding ASCII
}

$protectedSecret = Get-Content -Path $SecretPath -Raw
$secureSecret = ConvertTo-SecureString $protectedSecret
$env:DASHBOARD_SESSION_SECRET = [System.Net.NetworkCredential]::new("", $secureSecret).Password
$env:COINBASE_KEY_FILE = [Environment]::GetEnvironmentVariable("COINBASE_KEY_FILE", "User")

Push-Location $ProjectRoot
try {
    "$(Get-Date -Format o) Starting Swingdesk on port $Port." | Add-Content -Path $LogPath
    & $Waitress --listen="0.0.0.0:$Port" --call "dashboard:create_app" *>> $LogPath
    if ($LASTEXITCODE -ne 0) {
        throw "Waitress exited with code $LASTEXITCODE."
    }
}
catch {
    "$(Get-Date -Format o) $($_.Exception.Message)" | Add-Content -Path $LogPath
    throw
}
finally {
    Pop-Location
    Remove-Item Env:DASHBOARD_SESSION_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:COINBASE_KEY_FILE -ErrorAction SilentlyContinue
}