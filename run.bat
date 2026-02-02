@echo off
echo ===================================================
echo        OpenMap Unifier - Startup Script
echo ===================================================
echo.
echo [INFO] Checking for libraries folder...
if exist "libraries" (
    echo [INFO] Found offline libraries.
) else (
    echo [INFO] No offline libraries found. Will attempt online install.
)

echo.
echo [STEP 1/2] Installing Dependencies...
echo.

:: Try installing from cached folder first
if exist "libraries" (
    echo [INFO] Installing from local 'libraries' folder...
    pip install --no-index --find-links=libraries customtkinter packaging requests shapely pyproj
    if %errorlevel% neq 0 (
        echo [WARNING] Local install had issues. Attempting standard install...
        pip install customtkinter packaging requests shapely pyproj
    )
) else (
    echo [INFO] Downloading and installing from PyPI...
    pip install customtkinter packaging requests shapely pyproj
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install dependencies.
    echo Please check your internet connection or Python installation.
    pause
    exit /b
)
echo [SUCCESS] Dependencies checked.

echo.
echo [STEP 2/2] Launching Application...
echo.

python gui.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application crashed or closed unexpectedly.
    pause
)
