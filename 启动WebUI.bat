@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting WeBan WebUI...
echo Access: http://127.0.0.1:8080
echo.
set WEBUI_PORT=8080
python webui.py
pause
