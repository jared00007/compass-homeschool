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

REM Creating a dotfile by hand is awkward on Windows, so ask and write it here.
if "%ANTHROPIC_API_KEY%"=="" (
    echo.
    echo   No API key set up yet.
    echo   Paste your Anthropic API key to enable lesson generation, or just press
    echo   Enter to skip - everything else in Compass works without one.
    echo.
    set /p "ENTERED=  API key: "
    if not "!ENTERED!"=="" (
        echo !ENTERED! | findstr /b "sk-ant-" >nul
        if errorlevel 1 (
            echo   [!] That doesn't look like an Anthropic key ^(they start with 'sk-ant-'^).
            echo       Skipping for now. Lesson generation will be off.
        ) else (
            > .env echo ANTHROPIC_API_KEY=!ENTERED!
            set "ANTHROPIC_API_KEY=!ENTERED!"
            echo   [OK] Saved to .env - you won't be asked again.
        )
    )
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo   [!] Running without an API key - lesson generation is off.
    echo       Everything else still works: the compliance dashboard, activity
    echo       log, math graph, choice topics, and life skills.
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
