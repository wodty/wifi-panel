@echo off
rem Register a logon task that starts the wifi-panel Agent silently (no window).
rem Run this AFTER you edited HUB / TOKEN / NAME in start_agent.bat.
chcp 65001 >nul
setlocal

set TASK=wifi-panel-agent
set HERE=%~dp0

schtasks /Create /F /SC ONLOGON /RL HIGHEST /TN %TASK% ^
  /TR "wscript.exe \"%HERE%start_agent_hidden.vbs\""
if errorlevel 1 (
  echo [error] create task failed. Try running this .bat as Administrator.
  pause
  exit /b 1
)
echo [ok] task "%TASK%" created. The agent will start silently at logon.
echo      Remove it anytime with uninstall_autostart.bat
pause
