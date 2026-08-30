param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$TaskName = "Swingdesk Dashboard"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PasswordHash = Join-Path $ProjectRoot "dashboard_password.json"
$Runner = Join-Path $ProjectRoot "run_dashboard_service.ps1"

if (-not (Test-Path $Python)) {
    throw "Dashboard dependencies are not installed. Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}
if (-not (Test-Path $PasswordHash)) {
    Push-Location $ProjectRoot
    try {
        & $Python ".\configure_dashboard_password.py"
        if ($LASTEXITCODE -ne 0) { throw "Password configuration failed." }
    }
    finally {
        Pop-Location
    }
}

$arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Runner`" -Port $Port"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -RestartCount 12 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Runs the local Swingdesk dashboard independently of VS Code." -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Swingdesk background service installed and started: http://127.0.0.1:$Port"