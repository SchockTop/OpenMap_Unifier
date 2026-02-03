@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo     OpenMap Unifier - Setup Script
echo ===================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: ===================================================
:: Step 1: Find Python Installation
:: ===================================================
echo [STEP 1/3] Checking for Python...

:: Check if venv already exists and works
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -c "import tkinter" 2>nul
    if !errorlevel! equ 0 (
        echo [OK] Virtual environment with tkinter found.
        goto :install_deps
    )
    echo [INFO] Existing venv is broken. Recreating...
    rmdir /s /q venv 2>nul
)

:: Try to find Python with tkinter
set "PYTHON_CMD="

:: Check common Python locations
for %%P in (
    "py -3.12"
    "py -3"
    "python"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) do (
    if not defined PYTHON_CMD (
        %%~P -c "import tkinter, venv" 2>nul && set "PYTHON_CMD=%%~P"
    )
)

if not defined PYTHON_CMD (
    echo.
    echo [ERROR] Python with tkinter not found!
    echo.
    echo This application requires Python 3.10+ with tkinter.
    echo.
    echo Please install Python from https://python.org
    echo IMPORTANT: During installation, check "Add Python to PATH"
    echo            and ensure "tcl/tk and IDLE" is selected.
    echo.
    echo After installing Python, run this script again.
    pause
    exit /b 1
)

echo [OK] Found Python: %PYTHON_CMD%

:: Verify tkinter works
%PYTHON_CMD% -c "import tkinter; print('[OK] tkinter is available')"
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Python found but tkinter is not available.
    echo Please reinstall Python with tcl/tk support.
    pause
    exit /b 1
)

:: ===================================================
:: Step 2: Create Virtual Environment
:: ===================================================
echo.
echo [STEP 2/3] Creating virtual environment...

%PYTHON_CMD% -m venv venv --system-site-packages

if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [OK] Virtual environment created.

:: ===================================================
:: Step 3: Install Dependencies
:: ===================================================
:install_deps
echo.
echo [STEP 3/3] Installing dependencies...

call venv\Scripts\activate.bat

:: Try offline first
if exist "libraries" (
    echo [INFO] Attempting offline installation from 'libraries' folder...
    pip install --no-index --find-links=libraries -r requirements.txt --upgrade --quiet 2>nul
    
    if !errorlevel! equ 0 (
        echo [OK] Offline installation successful.
        goto :verify
    )
    
    echo [WARNING] Some packages not found offline. Falling back to online...
)

:: Online fallback
echo [INFO] Installing from PyPI...
pip install -r requirements.txt --upgrade --quiet

if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo [OK] Dependencies installed.

:: ===================================================
:: Verification
:: ===================================================
:verify
echo.
echo [INFO] Verifying installation...

python -c "import customtkinter; import PIL; import requests; import shapely; import pyproj; print('[OK] All core modules imported successfully.')"

if %errorlevel% neq 0 (
    echo [WARNING] Some modules failed to import.
) else (
    echo [OK] Verification passed.
)

call venv\Scripts\deactivate.bat 2>nul

echo.
echo ===================================================
echo     Setup Complete!
echo ===================================================
echo.
echo You can now run the application using:
echo   - run.bat          (GUI application)
echo   - run_web.bat      (Web server)
echo.
pause
