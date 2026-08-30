$ErrorActionPreference = "Stop"
$TaskName = "Swingdesk Dashboard"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Host "Swingdesk background service removed. Local settings and password hash were preserved."