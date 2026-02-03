@echo off
setlocal

echo ===================================================
echo     OpenMap Unifier - GUI Application
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Running setup...
    echo.
    call setup.bat
    if %errorlevel% neq 0 (
        echo [ERROR] Setup failed. Cannot continue.
        pause
        exit /b 1
    )
)

:: Activate and run
call venv\Scripts\activate.bat

echo [INFO] Starting OpenMap Unifier...
python gui.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application crashed or closed unexpectedly.
    echo [INFO] Check the console output above for details.
    pause
)

call venv\Scripts\deactivate.bat 2>nul
