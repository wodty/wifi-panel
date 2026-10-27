@echo off
rem wifi-panel PC Agent launcher (can be placed into shell:startup)
rem Edit HUB below to your hub address, e.g. ws://192.168.1.100:8765/ws/agent
cd /d %~dp0..

set HUB=ws://192.168.9.61:8765/ws/agent
set TOKEN=panel123

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating venv ...
    python -m venv .venv || (echo [error] python not found in PATH & pause & exit /b 1)
)

".venv\Scripts\python.exe" -c "import pynput" 2>nul || (
    echo [setup] installing dependencies ...
    ".venv\Scripts\python.exe" -m pip install -q -r agent\requirements.txt
)

echo [run] agent connecting to %HUB%
".venv\Scripts\python.exe" agent\agent.py %HUB% %TOKEN%
pause
