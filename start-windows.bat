@echo off
rem bufferradio launcher for Windows: double-click this file.
rem Finds (or installs) Python, sets up a private environment with all
rem dependencies on the first run, then starts the player.
setlocal
cd /d "%~dp0"
title bufferradio
echo === bufferradio ===

rem --- 1. find a Python 3.12+ interpreter ---------------------------------
set "PY="
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if defined PY "%PY%" -c "import sys; sys.exit(sys.version_info < (3, 12))" 2>nul || set "PY="
if defined PY goto :have_python

echo Python is not installed. Installing it now (one time, about a minute)...
winget install -e --id Python.Python.3.13 --scope user --accept-source-agreements --accept-package-agreements
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PY=%%~D\python.exe"
if defined PY if exist "%PY%" goto :have_python
echo.
echo Could not install Python automatically.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then double-click this file again.
goto :fail

:have_python
rem --- 2. private environment + dependencies (fast if already done) --------
if not exist ".venv\Scripts\python.exe" (
    echo Setting up a private Python environment - one time only...
    "%PY%" -m venv .venv || goto :fail
)
set "VPY=%CD%\.venv\Scripts\python.exe"
echo Checking dependencies...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt || goto :fail

rem --- 3. play -------------------------------------------------------------
rem Double-clicked (no arguments): open the web page. Otherwise pass the
rem arguments through, e.g.  start-windows.bat --station fip
echo.
if "%~1"=="" (
    "%VPY%" run.py --web
) else (
    "%VPY%" run.py %*
)
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
