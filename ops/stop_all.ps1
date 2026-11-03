# Stops what start_all.ps1 started. Doesn't touch MongoDB, HDFS or YARN.
$patterns = 'serve.py --port', 'backend\collector.py', 'ops\health_monitor.py --loop', 'deploy/apache/httpd.conf'
Get-CimInstance Win32_Process | Where-Object {
    $commandLine = $_.CommandLine
    $_.ProcessId -ne $PID -and $commandLine -and ($patterns | Where-Object { $commandLine -like "*$_*" })
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "Stopped $($_.Name) ($($_.ProcessId))"
}
