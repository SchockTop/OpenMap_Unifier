@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo     OpenMap Unifier - Web Server
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Running setup...
    call setup.bat
    if %errorlevel% neq 0 (
        echo [ERROR] Setup failed.
        pause
        exit /b 1
    )
)

:: Activate venv
call venv\Scripts\activate.bat

:: Check if web dependencies are installed
python -c "import fastapi; import uvicorn" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing web server dependencies...
    
    if exist "libraries" (
        pip install --no-index --find-links=libraries -r requirements-web.txt --quiet 2>nul
        if !errorlevel! neq 0 (
            pip install -r requirements-web.txt --quiet
        )
    ) else (
        pip install -r requirements-web.txt --quiet
    )
    
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install web dependencies.
        pause
        exit /b 1
    )
)

echo.
echo [INFO] Starting web server on http://127.0.0.1:8000
echo [INFO] Press Ctrl+C to stop.
echo.

python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload

call venv\Scripts\deactivate.bat 2>nul
