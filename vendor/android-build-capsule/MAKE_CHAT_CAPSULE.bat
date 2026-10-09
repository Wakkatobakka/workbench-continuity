@echo off
setlocal
cd /d "%~dp0"
echo WAKKA Android Build Capsule - private chat runtime maker
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Make-Chat-Capsule.ps1"
if errorlevel 1 (
  echo.
  echo Setup stopped. Your existing Capsule has not been changed.
)
echo.
pause
