@echo off
rem wifi-panel hub launcher (local test; for NAS use docker compose)
rem Auto-creates .venv and installs deps on first run.
cd /d %~dp0

if not exist ".venv\Scripts\python.exe" (
    echo [setup] creating venv ...
    python -m venv .venv || (echo [error] python not found in PATH & pause & exit /b 1)
)

".venv\Scripts\python.exe" -c "import fastapi" 2>nul || (
    echo [setup] installing dependencies ...
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)

echo [run] hub on http://0.0.0.0:8765  (token from PANEL_TOKEN env or default panel123)
".venv\Scripts\python.exe" -m uvicorn server.main:app --host 0.0.0.0 --port 8765
pause
