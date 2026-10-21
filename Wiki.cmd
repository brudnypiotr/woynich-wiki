@echo off
rem Wiki: double-click me (or the desktop shortcut setup.cmd made) to start the app and open it in the browser.
rem Another knowledge base: "Wiki.cmd" C:\kb\other-instance  (sets KB_INSTANCE for this window only)
rem After Update in the app, kb serve exits with code 3 and this window starts it again.
rem An update may replace this file while it runs, and cmd reads a running script line by line from disk: so it runs
rem from a copy in %TEMP% and finds the app through KB_REPO.
if defined KB_REPO goto copied
set "KB_REPO=%~dp0"
rem one copy per app folder (two folders may hold different versions of this script): C:\kb\app\ -> C-kb-app-
set "KB_NAME=%~dp0"
set "KB_NAME=%KB_NAME::=%"
set "KB_NAME=%KB_NAME:\=-%"
set "KB_NAME=%KB_NAME: =_%"
set "KB_COPY=%TEMP%\wiki-%KB_NAME%.cmd"
copy /y "%~f0" "%KB_COPY%" >nul || goto copied
"%KB_COPY%" %*

:copied
setlocal
title Wiki
if not defined KB_REPO set "KB_REPO=%~dp0"
if not "%~1"=="" set "KB_INSTANCE=%~f1"
cd /d "%KB_REPO%"
if not exist "%KB_REPO%kb.cmd" (
  echo kb.cmd not found: run setup.cmd first.
  pause
  exit /b 1
)
if defined KB_INSTANCE echo Knowledge base: %KB_INSTANCE%
set "KB_LAUNCHER=1"

:start
call "%KB_REPO%kb.cmd" serve
set RC=%ERRORLEVEL%
if "%RC%"=="3" (
  call "%KB_REPO%kb.cmd" update --finish
  goto start
)
if "%RC%"=="0" exit /b 0

echo.
echo Wiki stopped with an error (%RC%). See the messages above.
echo If the fix is already published, an update may solve it.
choice /c UQ /n /m "Press U to update and start again, or Q to quit: "
if errorlevel 2 exit /b %RC%
call "%KB_REPO%kb.cmd" update
if errorlevel 1 (
  echo Update did not work. Run doctor.cmd and send doctor-report.json for help.
  pause
  exit /b %RC%
)
goto start
