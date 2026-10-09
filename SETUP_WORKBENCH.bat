@echo off
setlocal
cd /d "%~dp0"
echo Workbench Continuity - first-time build tools setup
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0vendor\android-build-capsule\tools\Make-Chat-Capsule.ps1"
echo.
echo When setup finishes, open Workbench and choose Load build runtime.
echo Select the new ZIP in vendor\android-build-capsule\Private_Capsules.
echo Keep that ZIP for later use. You do not need a separate Build Capsule download.
pause
