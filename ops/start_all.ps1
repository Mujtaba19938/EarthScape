# Starts both backend instances, the live data collector, the health monitor and Apache, each in the background.
# HDFS and YARN are started separately: see the installation steps.
param([string]$ApacheDir = 'C:\Apache24')

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force (Join-Path $logs 'apache') | Out-Null

function Test-Running($pattern) {
    @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$pattern*" -and $_.ProcessId -ne $PID }).Count -gt 0
}

function Start-Background($name, $pattern, $file, $arguments) {
    if (Test-Running $pattern) { Write-Output "$name is already running"; return }
    Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "$name.out.log") -RedirectStandardError (Join-Path $logs "$name.err.log")
    Write-Output "Started $name"
}

Start-Background 'backend-8000' 'serve.py --port 8000' $python 'backend\serve.py --port 8000'
Start-Background 'backend-8001' 'serve.py --port 8001' $python 'backend\serve.py --port 8001'
Start-Background 'collector' 'backend\collector.py' $python 'backend\collector.py'
Start-Background 'monitor' 'ops\health_monitor.py --loop' $python 'ops\health_monitor.py --loop 60'

$httpd = Join-Path $ApacheDir 'bin\httpd.exe'
if (-not (Test-Path $httpd)) {
    Write-Output "Apache not found at $httpd, so the site is only on http://127.0.0.1:8000 and :8001"
} elseif (Test-Running 'deploy/apache/httpd.conf') {
    Write-Output 'Apache is already running'
} else {
    $rootForward = $root -replace '\\', '/'
    $apacheForward = $ApacheDir -replace '\\', '/'
    Start-Process -FilePath $httpd -WindowStyle Hidden -ArgumentList @(
        '-d', "`"$apacheForward`"", '-f', "`"$rootForward/deploy/apache/httpd.conf`"", '-C', "`"Define EARTHSCAPE_ROOT $rootForward`"")
    Write-Output 'Started Apache: https://localhost'
}
