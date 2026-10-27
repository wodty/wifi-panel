@echo off
rem wifi-panel PC Agent launcher (foreground, for first-time setup / debugging)
rem 1) set HUB   to your hub address, e.g. ws://192.168.1.100:8765/ws/agent
rem 2) set TOKEN to your PANEL_TOKEN
rem 3) set NAME  to a friendly name shown on the phone (multiple PCs = multiple names)
chcp 65001 >nul
cd /d %~dp0..

set HUB=ws://192.168.9.61:8765/ws/agent
set TOKEN=panel123
set NAME=客厅主机

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating venv ...
    python -m venv .venv || (echo [error] python not found in PATH & pause & exit /b 1)
)

".venv\Scripts\python.exe" -c "import pynput" 2>nul || (
    echo [setup] installing dependencies ...
    ".venv\Scripts\python.exe" -m pip install -q -r agent\requirements.txt
)

set NAMEARG=
if not "%NAME%"=="" set NAMEARG=--name %NAME%

echo [run] agent %NAME% connecting to %HUB%
".venv\Scripts\python.exe" agent\agent.py %HUB% %TOKEN% %NAMEARG%

rem called from start_agent_hidden.vbs: window is already hidden, no pause needed
if /i "%1"=="hidden" exit /b 0
pause
