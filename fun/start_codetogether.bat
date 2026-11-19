@echo off
setlocal
cd /d "%~dp0"

if not exist ".env" (
    echo ERROR: .env was not found.
    echo Copy .env.example to .env and configure the three accounts first.
    pause
    exit /b 1
)

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "INSTALL_REQUIREMENTS=0"

if exist "%VENV_PYTHON%" goto check_venv

set "PYTHON_COMMAND=py -3"
where py >nul 2>nul
if errorlevel 1 set "PYTHON_COMMAND=python"

%PYTHON_COMMAND% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 goto python_version_error

%PYTHON_COMMAND% -m venv .venv
if errorlevel 1 goto setup_error
set "INSTALL_REQUIREMENTS=1"

:check_venv
if not exist "%~dp0.venv\Scripts\uvicorn.exe" set "INSTALL_REQUIREMENTS=1"

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 goto python_version_error

if "%INSTALL_REQUIREMENTS%"=="1" (
    echo Installing project dependencies for the first run...
    "%VENV_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto setup_error
)

echo Starting CodeTogether for your local network.
echo On this network, open http://10.2.10.21:8000
echo This is plain HTTP. Coding-tab sharing requires HTTPS from other devices.
echo Do not port-forward this port or expose it to the public internet.
echo Press Ctrl+C in this window to stop the server.
"%VENV_PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --ws-max-size 131072
if errorlevel 1 goto server_error
exit /b 0

:python_version_error
echo ERROR: Python 3.12 or newer is required.
echo Install Python 3.12+ and try again.
pause
exit /b 1

:setup_error
echo ERROR: Project setup failed. Check Python and your internet connection.
pause
exit /b 1

:server_error
echo The server stopped with an error. Check the messages above.
pause
exit /b 1
