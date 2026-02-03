@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo     OpenMap Unifier - OFFLINE Mode
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Strict offline mode
if not exist "libraries" (
    echo [ERROR] 'libraries' folder not found!
    echo [INFO] Use 'download_libraries.bat' on a machine with internet first.
    pause
    exit /b 1
)

:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found.
    echo [INFO] Running setup (will use offline libraries)...
    call setup.bat
    if %errorlevel% neq 0 (
        echo [ERROR] Setup failed.
        pause
        exit /b 1
    )
)

:: Activate and run
call venv\Scripts\activate.bat

:: Verify offline packages
pip install --no-index --find-links=libraries -r requirements.txt --quiet 2>nul

echo [INFO] Starting OpenMap Unifier...
python gui.py

call venv\Scripts\deactivate.bat 2>nul
pause
