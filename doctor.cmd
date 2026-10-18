@echo off
rem woynich-wiki doctor: read-only check of this machine. Changes nothing.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\doctor.ps1" %*
echo.
pause
