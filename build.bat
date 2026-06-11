@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python environment was not found.
    echo Run this first: uv venv ^&^& uv pip install -r requirements-dev.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller ^
  -y ^
  --name info-hub ^
  --onedir ^
  --workpath release\build ^
  --distpath release\dist ^
  --add-data "src\static;static" ^
  --paths src ^
  --hidden-import database ^
  --hidden-import config ^
  --hidden-import scheduler ^
  --hidden-import fetchers.rss ^
  --hidden-import fetchers.github ^
  --hidden-import fetchers.hackernews ^
  --hidden-import fetchers.arxiv ^
  --hidden-import routers.api ^
  --hidden-import routers.sse ^
  src\main.py

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [Build] Failed. Exit code: %EXIT_CODE%
    pause
    exit /b %EXIT_CODE%
)

echo [Build] Done: release\dist\info-hub\
echo [Build] Run: release\dist\info-hub\info-hub.exe
pause
