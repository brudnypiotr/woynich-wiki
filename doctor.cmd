@echo off
rem woynich-wiki doctor: read-only check of this machine. Changes nothing.
setlocal
cd /d "%~dp0"
rem Started from PowerShell 7, the inherited PSModulePath breaks Windows PowerShell 5.1 modules: reset it.
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\doctor.ps1" %*
echo.
pause
