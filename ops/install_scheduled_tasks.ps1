# Adds EarthScape's tasks to Windows Task Scheduler. Run once from an administrator PowerShell.
# Remove them later with: Unregister-ScheduledTask -TaskName 'EarthScape*' -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root 'backend\.venv\Scripts\pythonw.exe'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'EarthScape Backup' -Force -Settings $settings `
    -Description 'Backs up MongoDB and HDFS exports, and checks that the backup restores.' `
    -Trigger (New-ScheduledTaskTrigger -Daily -At 2am) `
    -Action (New-ScheduledTaskAction -Execute $pythonw -Argument 'ops\backup.py' -WorkingDirectory $root) | Out-Null

Register-ScheduledTask -TaskName 'EarthScape Services' -Force -Settings $settings `
    -Description 'Starts the EarthScape website, collector, health monitor and Apache at sign-in.' `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) `
    -Action (New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\ops\start_all.ps1`"") | Out-Null

Get-ScheduledTask -TaskName 'EarthScape*' | Select-Object TaskName, State
