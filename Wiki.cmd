@echo off
rem Wiki: double-click me (or the desktop shortcut) to start the app and open it in the browser. The only script a user
rem needs: on the first start, or when a new version needs it (setup\version.txt changed), it runs the setup first.
rem It starts the app without a console window: an icon in the notification area (kb tray) runs it, restarts it after
rem an update and has Open, Show log, Restart and Quit. Logs: local\logs\serve.log and tray.log.
rem   Wiki.cmd --console              the app in this window with its output (for debugging); after Update in the
rem                                   app kb serve exits with code 3 and this window starts it again
rem   Wiki.cmd C:\kb\other-instance   another knowledge base (sets KB_INSTANCE for this start only)
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
if "%~1"=="--ready" goto ready_only
set "KB_CONSOLE="
if /i "%~1"=="--console" (set "KB_CONSOLE=1" & shift)
if not "%~1"=="" set "KB_INSTANCE=%~f1"
cd /d "%KB_REPO%"
if defined KB_INSTANCE echo Knowledge base: %KB_INSTANCE%
set "KB_LAUNCHER=1"

:start
call :ready || call :setup || exit /b 1
if not defined KB_CONSOLE goto tray
:serve
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

rem Wiki.cmd --ready: exit code 0 when the setup is done for this version (CI checks it), 1 when the next start runs it.
:ready_only
call :ready
exit /b %ERRORLEVEL%

rem The app in the background with a tray icon (pythonw: no console). Setup writes where pythonw.exe is.
:tray
set "PYW="
if exist "%KB_REPO%local\pythonw.txt" set /p PYW=<"%KB_REPO%local\pythonw.txt"
if not defined PYW goto serve
if not exist "%PYW%" goto serve
set "PYTHONUTF8=1"
start "" "%PYW%" -c "import sys; sys.path.insert(0, r'%KB_REPO%.'); from kb.cli import main; sys.exit(main())" tray
exit /b 0

rem Setup is done for this version: kb.cmd exists and local\setup-version.txt matches setup\version.txt.
:ready
if not exist "%KB_REPO%kb.cmd" exit /b 1
if not exist "%KB_REPO%local\setup-version.txt" exit /b 1
set "NEED=" & set "HAVE="
set /p NEED=<"%KB_REPO%setup\version.txt"
set /p HAVE=<"%KB_REPO%local\setup-version.txt"
if not "%NEED%"=="%HAVE%" exit /b 1
exit /b 0

:setup
echo Preparing this computer first (a few minutes, no admin rights needed). The app starts when it is done.
setlocal
rem Started from PowerShell 7, the inherited PSModulePath breaks Windows PowerShell 5.1 modules: reset it.
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%KB_REPO%setup\setup.ps1" -FromLauncher
set RC=%ERRORLEVEL%
endlocal & set RC=%RC%
if "%RC%"=="0" exit /b 0
echo.
echo Setup did not finish (%RC%). See the messages above and send setup.log (in %KB_REPO%) for help.
pause
exit /b 1
