param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Waitress = Join-Path $ProjectRoot ".venv\Scripts\waitress-serve.exe"

if (-not (Test-Path $Waitress)) {
    throw "Dashboard dependencies are not installed. Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

$securePassword = Read-Host "Create a dashboard password for this session" -AsSecureString
$password = [System.Net.NetworkCredential]::new("", $securePassword).Password
if ([string]::IsNullOrWhiteSpace($password)) {
    throw "Dashboard password cannot be empty."
}

$env:DASHBOARD_PASSWORD = $password
$env:DASHBOARD_SESSION_SECRET = [Guid]::NewGuid().ToString("N") + [Guid]::NewGuid().ToString("N")
$localUrl = "http://127.0.0.1:$Port"
$lanAddress = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred |
    Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress

Write-Host "Windows: $localUrl"
if ($lanAddress) {
    Write-Host "Android: http://${lanAddress}:$Port"
}
Write-Host "Press Ctrl+C to stop Swingdesk."
Start-Process $localUrl

Push-Location $ProjectRoot
try {
    & $Waitress --listen="0.0.0.0:$Port" --call "dashboard:create_app"
}
finally {
    Pop-Location
    Remove-Item Env:DASHBOARD_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:DASHBOARD_SESSION_SECRET -ErrorAction SilentlyContinue
}