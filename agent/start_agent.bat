@echo off
rem ============================================================
rem  wifi-panel PC Agent launcher (foreground, for first-time run)
rem
rem  EDIT THESE 3 LINES BELOW before first run:
rem    HUB   - your hub address, e.g. ws://192.168.9.61:8765/ws/agent
rem    TOKEN - your PANEL_TOKEN
rem    NAME  - friendly name shown on the phone
rem
rem  IMPORTANT: keep this file ASCII-only.
rem  If you want a Chinese NAME, save this file as ANSI encoding
rem  (Notepad: Save As -> Encoding = ANSI), do NOT keep UTF-8.
rem ============================================================
cd /d "%~dp0.."

set HUB=ws://192.168.9.61:8765/ws/agent
set TOKEN=panel123
set NAME=LivingRoom-PC

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating venv ...
    python -m venv .venv || (echo [error] python not found in PATH & pause & exit /b 1)
)

".venv\Scripts\python.exe" -c "import pynput" 2>nul || (
    echo [setup] installing dependencies ...
    ".venv\Scripts\python.exe" -m pip install -q -r "%~dp0requirements.txt"
)

set NAMEARG=
if not "%NAME%"=="" set NAMEARG=--name %NAME%

echo [run] agent %NAME% connecting to %HUB%
".venv\Scripts\python.exe" "%~dp0agent.py" %HUB% %TOKEN% %NAMEARG%

rem called from start_agent_hidden.vbs: window is already hidden, no pause needed
if /i "%1"=="hidden" exit /b 0
pause
