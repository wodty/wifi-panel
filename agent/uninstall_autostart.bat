@echo off
rem Remove the logon autostart task created by install_autostart.bat
chcp 65001 >nul
schtasks /Delete /F /TN wifi-panel-agent
if errorlevel 1 (
  echo [error] task not found or delete failed.
) else (
  echo [ok] autostart task removed.
)
pause
