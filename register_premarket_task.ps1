# Registers a Windows scheduled task that runs run_premarket.bat on weekdays at 08:30.
# Usage (PowerShell, in this folder):
#   powershell -ExecutionPolicy Bypass -File .\register_premarket_task.ps1
# Remove it later with:
#   Unregister-ScheduledTask -TaskName JpStockPremarket -Confirm:$false
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$bat = Join-Path $dir 'run_premarket.bat'
if (-not (Test-Path $bat)) { throw "run_premarket.bat was not found in $dir" }

$action   = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 8:30am
# StartWhenAvailable: if the PC was off/asleep at 08:30, run as soon as it is available.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'JpStockPremarket' -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Japan stock day-close research: pre-market environment update (US market -> expected gap).' -Force | Out-Null

Write-Host 'Registered: JpStockPremarket (weekdays 08:30). To test now:'
Write-Host '  Start-ScheduledTask -TaskName JpStockPremarket'
Write-Host "Log: $dir\logs\run_premarket.log"
