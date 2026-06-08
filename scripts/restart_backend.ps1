param(
    [int]$Port = 8000,
    [switch]$NoStart,
    [switch]$Foreground
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
$ServerScript = Join-Path $Root "backend\server.py"

function Stop-AiNewsPythonProcesses {
    $patterns = @(
        "*backend/server.py*",
        "*backend\server.py*",
        "*backend/Generator.py*",
        "*backend\Generator.py*"
    )

    $processes = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
        Where-Object {
            $cmd = $_.CommandLine
            $patterns | Where-Object { $cmd -like $_ }
        }

    foreach ($process in $processes) {
        Write-Host "Stopping PID $($process.ProcessId): $($process.CommandLine)"
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Wait-PortFree {
    param([int]$Port)

    for ($i = 0; $i -lt 20; $i++) {
        $listener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -eq $Port }
        if (-not $listener) {
            return
        }
        Start-Sleep -Milliseconds 500
    }

    $listener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $Port } |
        Select-Object -First 1
    if ($listener) {
        throw "Port $Port is still busy by PID $($listener.OwningProcess)."
    }
}

Stop-AiNewsPythonProcesses
Wait-PortFree -Port $Port

if ($NoStart) {
    Write-Host "Stopped backend processes. Port $Port is free."
    exit 0
}

if (-not (Test-Path $VenvPython)) {
    throw "Could not find venv Python at $VenvPython"
}

Write-Host "Starting backend on http://127.0.0.1:$Port ..."
if ($Foreground) {
    Write-Host "Running in foreground. Press Ctrl+C to stop."
    & $VenvPython "backend/server.py"
    exit $LASTEXITCODE
}

Start-Process -FilePath $VenvPython -ArgumentList "backend/server.py" -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 3

$listener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -eq $Port } |
    Select-Object -First 1
if (-not $listener) {
    throw "Backend did not start on port $Port."
}

$health = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/news?auto=0" -TimeoutSec 10
Write-Host "Backend is ready. HTTP $($health.StatusCode)"
Write-Host "Open: http://127.0.0.1:$Port/UI.html"
