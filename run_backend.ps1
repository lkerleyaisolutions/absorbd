<#
.SYNOPSIS
  Free port 8000, then launch the Absorbd backend (uvicorn --reload).

.WHY
  uvicorn --reload spawns a reloader parent + a worker child. The worker is a
  `python -c "from multiprocessing.spawn import spawn_main ..."` process whose
  command line contains NEITHER "uvicorn" NOR "main:app". If the parent dies
  badly (orphaned across sessions), that worker keeps the listening socket on
  8000 alive and hides from a naive `*uvicorn*` process filter. The result is a
  stale server that answers requests with OLD code while your edits appear to do
  nothing. This script kills those stragglers too, so every launch is clean.

.USAGE
  From the absorb-iq directory:  .\run_backend.ps1
  Optional port:                 .\run_backend.ps1 -Port 8000
#>

param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$python = Join-Path $root 'venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host "ERROR: venv python not found at $python" -ForegroundColor Red
    Write-Host "Create it first:  python -m venv venv ; venv\Scripts\pip install -r requirements.txt"
    exit 1
}

function Get-ListenerPids {
    param([int]$Port)
    $found = @()
    # Primary: the TCP table.
    try {
        $found += Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                  Select-Object -ExpandProperty OwningProcess
    } catch {}
    # Fallback: netstat (occasionally lists a holder Get-NetTCPConnection misses).
    try {
        $found += netstat -ano |
                  Select-String ":$Port\s" |
                  Where-Object { $_ -match 'LISTENING' } |
                  ForEach-Object { ($_ -split '\s+')[-1] }
    } catch {}
    $found | Where-Object { $_ -match '^\d+$' -and $_ -ne '0' } | Sort-Object -Unique
}

function Stop-UvicornStragglers {
    # Kill: (a) uvicorn reloaders, (b) anything running our app, and (c) ORPHANED
    # multiprocessing spawn workers — the ones that keep the socket alive after
    # their parent reloader is already gone.
    $alivePythonPids = @((Get-Process -Name python -ErrorAction SilentlyContinue).Id)
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -like '*uvicorn*' -or
                $_.CommandLine -like '*main:app*' -or
                ($_.CommandLine -like '*spawn_main*' -and ($alivePythonPids -notcontains $_.ParentProcessId))
            )
        } |
        ForEach-Object {
            taskkill /PID $_.ProcessId /T /F *> $null
            Write-Host "  killed python PID $($_.ProcessId)" -ForegroundColor DarkGray
        }
}

Write-Host "Freeing port $Port ..." -ForegroundColor Cyan
for ($i = 0; $i -lt 10; $i++) {
    Stop-UvicornStragglers
    foreach ($procId in (Get-ListenerPids -Port $Port)) {
        taskkill /PID $procId /T /F *> $null
    }
    Start-Sleep -Milliseconds 600
    if (-not (Get-ListenerPids -Port $Port)) { break }
}

if (Get-ListenerPids -Port $Port) {
    Write-Host "WARNING: port $Port still shows a listener; starting anyway." -ForegroundColor Yellow
} else {
    Write-Host "Port $Port is free." -ForegroundColor Green
}

Write-Host "Starting backend on port $Port (uvicorn main:app --reload)" -ForegroundColor Cyan
Set-Location $root
& $python -m uvicorn main:app --port $Port --reload
