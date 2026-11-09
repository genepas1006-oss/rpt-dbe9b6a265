# Registers a Windows scheduled task that runs run_daily.bat on weekdays at 16:10.
# Usage (PowerShell, in this folder):
#   powershell -ExecutionPolicy Bypass -File .\register_daily_task.ps1
# Remove it later with:
#   Unregister-ScheduledTask -TaskName JpStockDaily -Confirm:$false
# run_daily.bat pulls the latest code (git pull) before running, so no manual step is needed.
# On market holidays no price data exists, so run_daily.py stops without publishing.
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$bat = Join-Path $dir 'run_daily.bat'
if (-not (Test-Path $bat)) { throw "run_daily.bat was not found in $dir" }

$action   = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 4:10pm
# StartWhenAvailable: if the PC was off/asleep at 16:10, run as soon as it is available.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'JpStockDaily' -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Japan stock day-close research: daily report (after market close).' -Force | Out-Null

Write-Host 'Registered: JpStockDaily (weekdays 16:10). To test now:'
Write-Host '  Start-ScheduledTask -TaskName JpStockDaily'
