@echo off
echo ===================================================
echo     OpenMap Unifier - OFFLINE Startup
echo ===================================================
echo.
echo [INFO] This script forces installation from the 'libraries' folder.
echo [INFO] Ensure you have copied the 'libraries' folder with this script.
echo.

if not exist "libraries" (
    echo [ERROR] 'libraries' folder not found!
    echo Please ensure the dependencies are downloaded next to this script.
    pause
    exit /b
)

echo [STEP 1/2] Installing Dependencies (Offline Mode)...
pip install --no-index --find-links=libraries customtkinter packaging requests shapely pyproj

if %errorlevel% neq 0 (
    echo [ERROR] Installation failed.
    pause
    exit /b
)

echo [STEP 2/2] Launching GUI...
python gui.py
pause
