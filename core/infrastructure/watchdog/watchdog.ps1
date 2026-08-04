<#
.SYNOPSIS
    Quant worker external watchdog — the last line of defense against silent death.

.DESCRIPTION
    The supervision tree (start.py -> supervisor) already detects child
    crashes and hangs via heartbeats. But if the SUPERVISOR itself dies or
    hangs, nothing inside the tree can restart it. This script runs
    OUTSIDE the tree (as a Windows Scheduled Task, every minute) and:

      1. Reads the supervisor's own heartbeat file
         (%LOCALAPPDATA%/Quant worker-Monitor/heartbeats/supervisor.json).
      2. If the file is MISSING or STALE (> StaleSeconds), the supervisor
         is dead or hung -> kill the whole process tree (supervisor +
         its children) and relaunch start.py with the PINNED interpreter.

    StaleSeconds is deliberately large (120s) because the supervisor
    writes its heartbeat every 5s; a 120s gap is unambiguous death, which
    avoids false-positive restarts during normal startup.

    This is the standard "watchdog outside the supervised tree" pattern
    (cf. systemd is itself supervised by the kernel; Docker daemons by
    init). No Python dependency — pure PowerShell.
#>

$ErrorActionPreference = "SilentlyContinue"

$ResearchRoot = "E:\Quant worker-CLEAN\wq-alpha-research"
$PanelRoot     = "E:\Quant worker-monitor-web-panel"
$Python        = "E:\Python311\python.exe"
$LocalAppData  = $env:LOCALAPPDATA
$HB            = Join-Path $LocalAppData "Quant worker-Monitor\heartbeats\supervisor.json"
$LogPath       = Join-Path $LocalAppData "Quant worker-Monitor\watchdog.log"
$StaleSeconds  = 120

function Write-Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try { Add-Content -Path $LogPath -Value "[$ts] $msg" } catch { }
}

$dead = $false
if (-not (Test-Path $HB)) {
    $dead = $true
    Write-Log "supervisor heartbeat MISSING -> restart tree"
} else {
    $age = (Get-Date) - (Get-Item $HB).LastWriteTime
    if ($age.TotalSeconds -gt $StaleSeconds) {
        $dead = $true
        Write-Log ("supervisor heartbeat STALE ({0:N0}s > {1}s) -> restart tree" -f $age.TotalSeconds, $StaleSeconds)
    }
}

if (-not $dead) { exit 0 }

# Kill the existing tree: supervisor + its supervised children. We match by
# command line so we don't touch unrelated python processes.
$targets = @("start.py", "project_runtime.py", "adapter_host.py", "panel_app.py")
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    $cl = $_.CommandLine
    foreach ($t in $targets) {
        if ($cl -and $cl.Contains($t)) {
            Write-Log ("killing PID {0} ({1})" -f $_.ProcessId, $t)
            try { Stop-Process -Id $_.ProcessId -Force } catch { }
        }
    }
}
Start-Sleep -Seconds 2

# Relaunch the supervisor with the pinned, dependency-complete interpreter.
Write-Log "relaunching start.py"
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Python
    $psi.Arguments = "`"$PanelRoot\start.py`""
    $psi.WorkingDirectory = $PanelRoot
    $psi.WindowStyle = "Hidden"
    $psi.UseShellExecute = $false
    [void][System.Diagnostics.Process]::Start($psi)
    Write-Log "relaunch issued"
} catch {
    Write-Log ("relaunch FAILED: {0}" -f $_.Exception.Message)
}
