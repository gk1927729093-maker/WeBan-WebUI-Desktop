@echo off
chcp 65001 > nul
title WeBan WebUI
echo ========================================
echo    WeBan WebUI Launcher
echo ========================================
echo.

REM Check Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

REM Check dependencies
echo [INFO] Checking dependencies...
python -c "import fastapi, uvicorn, tomli_w" 2>nul
if errorlevel 1 (
    echo [WARN] Missing dependencies. Installing...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
)

echo [INFO] Starting WeBan WebUI...
echo [INFO] Access at: http://127.0.0.1:8080
echo [INFO] Press Ctrl+C to stop
echo.

python webui.py

if errorlevel 1 (
    echo.
    echo [ERROR] WebUI exited with error
    pause
)
