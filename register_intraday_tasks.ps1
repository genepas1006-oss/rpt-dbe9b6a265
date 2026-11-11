# Registers two Windows scheduled tasks: the opening-gap slot (weekdays 09:25) and the lunch-break slot (weekdays 11:50).
# Usage (PowerShell, in this folder):
#   powershell -ExecutionPolicy Bypass -File .\register_intraday_tasks.ps1
# Remove them later with:
#   Unregister-ScheduledTask -TaskName JpStockOpen -Confirm:$false
#   Unregister-ScheduledTask -TaskName JpStockLunch -Confirm:$false
# Each .bat pulls the latest code (git pull) before running. On market holidays no price data exists, so the run stops without publishing.
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$days = 'Monday','Tuesday','Wednesday','Thursday','Friday'
# StartWhenAvailable is intentionally NOT set: a late run (after the window) would publish stale data.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

foreach ($t in @(
    @{ Name = 'JpStockOpen';  Bat = 'run_open.bat';  At = '9:25am';  Desc = 'Japan stock research: opening-gap slot (trial).' },
    @{ Name = 'JpStockLunch'; Bat = 'run_lunch.bat'; At = '11:50am'; Desc = 'Japan stock research: lunch-break slot (trial).' }
)) {
    $bat = Join-Path $dir $t.Bat
    if (-not (Test-Path $bat)) { throw "$($t.Bat) was not found in $dir" }
    $action  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $dir
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $t.At
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Description $t.Desc -Force | Out-Null
    Write-Host "Registered: $($t.Name) (weekdays $($t.At)). To test now: Start-ScheduledTask -TaskName $($t.Name)"
}
