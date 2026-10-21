@echo off
rem Wiki: download and install the newest version (the same as Update in the app). Close the app first.
setlocal
cd /d "%~dp0"
if not exist "%~dp0kb.cmd" (
  echo kb.cmd not found: run setup.cmd first.
  pause
  exit /b 1
)
call "%~dp0kb.cmd" update
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo Done. Start Wiki again.) else (echo Update did not work. Run doctor.cmd and send doctor-report.json for help.)
pause
exit /b %RC%
