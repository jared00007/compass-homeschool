@echo off
REM Compass launcher - Windows. Double-click this file.
REM
REM   run.bat          open on this computer only
REM   run.bat --lan    also reachable from other devices on the same network

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo   Starting Compass
echo.

REM --- Python ---------------------------------------------------------------

where python >nul 2>&1
if errorlevel 1 (
    echo   [X] Python is not installed.
    echo       Install Python 3.10 or newer from python.org, then run this again.
    echo       IMPORTANT: tick "Add Python to PATH" in the installer.
    pause
    exit /b 1
)

REM --- Virtualenv + dependencies --------------------------------------------

if not exist ".venv" (
    echo   First run - setting up. This takes a minute, only once.
    python -m venv .venv
    if errorlevel 1 ( echo   [X] Could not create the virtual environment. & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat

python -c "import streamlit, anthropic" >nul 2>&1
if errorlevel 1 (
    echo   Installing dependencies...
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r requirements.txt
    if errorlevel 1 ( echo   [X] Dependency install failed. & pause & exit /b 1 )
)
echo   [OK] Dependencies ready

REM Streamlit prompts for an email on first run and blocks waiting for input,
REM which looks like a hang in a double-clicked window. Skip it permanently.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    (
        echo [general]
        echo email = ""
    ) > "%USERPROFILE%\.streamlit\credentials.toml"
)

REM --- API key --------------------------------------------------------------

if "%ANTHROPIC_API_KEY%"=="" (
    if exist ".env" (
        for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
            if /i "%%a"=="ANTHROPIC_API_KEY" set "ANTHROPIC_API_KEY=%%b"
        )
    )
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo   [!] No API key found - lesson generation will be turned off.
    echo       Everything else still works.
    echo       To turn it on, create a file called .env next to this script
    echo       containing one line:  ANTHROPIC_API_KEY=sk-ant-...
) else (
    echo   [OK] API key loaded
)

REM --- Network mode ---------------------------------------------------------

set "ADDRESS=localhost"
if "%~1"=="--lan" (
    set "ADDRESS=0.0.0.0"
    echo.
    echo   On his tablet or laptop, use this computer's network address on port 8501.
    echo   Run  ipconfig  in another window to find it ^(IPv4 Address^).
    echo   Both devices must be on the same wifi.
)

echo.
echo   Opening Compass. Leave this window open while using it.
echo   Press Ctrl-C here when finished.
echo.

streamlit run Home.py --server.address %ADDRESS% --server.port 8501 --server.headless false
pause
