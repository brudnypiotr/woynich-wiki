@echo off
rem woynich-wiki: double-click me to start the app (kb serve) and open it in the browser.
rem Another knowledge base: serve.cmd C:\kb\other-instance  (sets KB_INSTANCE for this window only)
setlocal
cd /d "%~dp0"
if not exist "%~dp0kb.cmd" (
  echo kb.cmd not found: run setup.cmd first.
  pause
  exit /b 1
)
if not "%~1"=="" set "KB_INSTANCE=%~f1"
if defined KB_INSTANCE echo Knowledge base: %KB_INSTANCE%
call "%~dp0kb.cmd" serve
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo kb serve stopped with an error ^(%RC%^). See the messages above.
  pause
)
exit /b %RC%
