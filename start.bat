@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python environment was not found.
    echo Run this first: uv venv ^&^& uv pip install -r requirements.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "start.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [Info Hub] Startup failed. Exit code: %EXIT_CODE%
    pause
)

exit /b %EXIT_CODE%
