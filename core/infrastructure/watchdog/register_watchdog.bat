@echo off
REM ---------------------------------------------------------------------------
REM Register the Quant worker external watchdog as a Windows Scheduled Task that
REM runs EVERY MINUTE. The watchdog checks the supervisor's heartbeat and
REM restarts the whole tree if it is dead/hung. This is the final
REM guarantee that the system self-heals even if the supervisor itself dies.
REM
REM Run this ONCE (as Administrator). It is idempotent (/F overwrites).
REM ---------------------------------------------------------------------------
set "PYTHON=E:\Python311\python.exe"
set "WATCHDOG=E:\Quant worker-CLEAN\wq-alpha-research\core\infrastructure\watchdog\watchdog.ps1"

schtasks /Create ^
  /TN "Quant workerWatchdog" ^
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"%WATCHDOG%\"" ^
  /SC MINUTE /MO 1 /F

if %ERRORLEVEL%==0 (
  echo.
  echo [OK] Watchdog registered. It will check the supervisor every minute.
  echo      Logs: %%LOCALAPPDATA%%\Quant worker-Monitor\watchdog.log
) else (
  echo.
  echo [FAIL] Could not register the scheduled task. Run this .bat as Administrator.
)
pause
