@echo off
rem woynich-wiki setup: double-click me. No admin rights needed.
rem Runs setup\setup.ps1 with ExecutionPolicy Bypass for this process only.
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\setup.ps1" %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo Setup finished. You can close this window.) else (echo Setup did not finish. See setup.log and send it for help.)
pause
exit /b %RC%
