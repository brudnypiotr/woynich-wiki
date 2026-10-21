@echo off
rem Wiki: run every test (setup.cmd runs only the 5 smoke tests). Changes nothing.
rem   test.cmd                 all tests
rem   test.cmd -m smoke        only the smoke tests
rem   test.cmd -k update       tests with "update" in the name
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\woynich-wiki\python312\python.exe"
if not exist "%PY%" (
  echo Python for this app not found: run setup.cmd first.
  pause
  exit /b 1
)
echo Running the tests with %PY%
echo This takes a few minutes on Windows ^(antivirus checks every file and process^).
echo.
"%PY%" -m pytest -v -p no:cacheprovider --color=yes %*
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (echo ALL TESTS PASSED.) else (echo SOME TESTS FAILED: see the red lines above.)
pause
exit /b %RC%
