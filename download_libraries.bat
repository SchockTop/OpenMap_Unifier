@echo off
setlocal

echo ===================================================
echo     OpenMap Unifier - Download Libraries
echo ===================================================
echo.
echo This script downloads all required wheels for offline deployment.
echo Requirements: Internet connection, Python 3.12 with pip.
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "libraries" mkdir libraries

:: Determine which Python to use
set "PYTHON_CMD=python"

if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
) else if exist "python\python.exe" (
    set "PYTHON_CMD=python\python.exe"
)

echo [INFO] Using Python: %PYTHON_CMD%
echo.

:: Download embedded Python if not present
echo [STEP 1/3] Checking for embedded Python archive...

set "PYTHON_VERSION=3.12.8"
set "PYTHON_ZIP=python-%PYTHON_VERSION%-embed-amd64.zip"

if exist "libraries\%PYTHON_ZIP%" (
    echo [OK] Embedded Python archive already present.
) else (
    echo [INFO] Downloading embedded Python %PYTHON_VERSION%...
    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%PYTHON_VERSION%/%PYTHON_ZIP%' -OutFile 'libraries\%PYTHON_ZIP%'}"
    
    if %errorlevel% neq 0 (
        echo [WARNING] Failed to download embedded Python.
    ) else (
        echo [OK] Downloaded embedded Python.
    )
)

:: Download wheels for core requirements
echo.
echo [STEP 2/3] Downloading core dependencies...

%PYTHON_CMD% -m pip download ^
    --dest libraries ^
    --only-binary :all: ^
    --platform win_amd64 ^
    --python-version 3.12 ^
    -r requirements.txt

if %errorlevel% neq 0 (
    echo [WARNING] Some core packages may have failed.
)

:: Download wheels for web requirements
echo.
echo [STEP 3/3] Downloading web server dependencies...

%PYTHON_CMD% -m pip download ^
    --dest libraries ^
    --only-binary :all: ^
    --platform win_amd64 ^
    --python-version 3.12 ^
    -r requirements-web.txt

if %errorlevel% neq 0 (
    echo [WARNING] Some web packages may have failed.
)

:: Also get pip and setuptools wheels
echo.
echo [INFO] Downloading pip and setuptools...

%PYTHON_CMD% -m pip download ^
    --dest libraries ^
    --only-binary :all: ^
    --platform win_amd64 ^
    --python-version 3.12 ^
    pip setuptools wheel

echo.
echo ===================================================
echo     Download Complete!
echo ===================================================
echo.
echo The 'libraries' folder now contains all wheels for offline deployment.
echo.
echo Contents:
dir /b libraries\*.whl 2>nul | find /c ".whl"
echo wheel files downloaded.
echo.
pause
