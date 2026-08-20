@echo off
chcp 65001 >nul
echo Starting WeBan WebUI...
echo.
set WEBUI_PORT=8088
python webui.py
pause
