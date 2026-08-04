@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
set "URL=http://127.0.0.1:8765"

start "Quant worker监控面板" /min "%PYTHON%" "%ROOT%panel_app.py"
timeout /t 3 >nul
start "" "%URL%"

endlocal
