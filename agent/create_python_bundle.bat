@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: Python 3.13 Bundle Creator for SentinelEdge
:: ============================================================================
:: Run this ONCE on a development machine to create the python313 folder
:: that will be shipped with the installer
:: ============================================================================

echo.
echo ========================================================================
echo   Python 3.13 Bundle Creator
echo ========================================================================
echo.

:: Check if we have internet access
ping -n 1 python.org >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] No internet connection - cannot download Python
    pause
    exit /b 1
)

:: Create temp directory
set "TEMP_DIR=%TEMP%\python313_bundle"
mkdir "%TEMP_DIR%" 2>nul

:: Download Python 3.13 embeddable package
echo [INFO] Downloading Python 3.13 embeddable package...
set "PYTHON_URL=https://www.python.org/ftp/python/3.13.1/python-3.13.1-embed-amd64.zip"
set "PYTHON_ZIP=%TEMP_DIR%\python313.zip"

powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ZIP%' -UseBasicParsing" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to download Python
    pause
    exit /b 1
)
echo [OK] Downloaded Python 3.13

:: Extract Python
echo [INFO] Extracting Python...
set "PYTHON_DIR=%~dp0python313"

if exist "%PYTHON_DIR%" (
    echo [INFO] Removing old python313 folder...
    rd /s /q "%PYTHON_DIR%"
)

powershell -Command "Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to extract Python
    pause
    exit /b 1
)
echo [OK] Extracted to: %PYTHON_DIR%

:: Configure Python for importing modules
echo [INFO] Configuring Python...

:: Create python313._pth file (tells Python where to find modules)
(
echo python313.zip
echo .
echo Lib
echo Lib\site-packages
echo import site
) > "%PYTHON_DIR%\python313._pth"

:: Download pip
echo [INFO] Installing pip...
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "GET_PIP=%TEMP_DIR%\get-pip.py"

powershell -Command "Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%GET_PIP%' -UseBasicParsing" 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to download pip
    pause
    exit /b 1
)

"%PYTHON_DIR%\python.exe" "%GET_PIP%" --no-warn-script-location >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install pip
    pause
    exit /b 1
)
echo [OK] pip installed

:: Install required packages
echo [INFO] Installing dependencies...
echo [INFO] This may take a few minutes...

"%PYTHON_DIR%\python.exe" -m pip install psutil pywin32 requests --no-warn-script-location --quiet 2>nul
if %errorlevel% neq 0 (
    echo [WARN] Some packages may have had issues, retrying...
    "%PYTHON_DIR%\python.exe" -m pip install psutil pywin32 requests --no-warn-script-location
)

:: pywin32 post-install
echo [INFO] Configuring pywin32...
if exist "%PYTHON_DIR%\Scripts\pywin32_postinstall.py" (
    "%PYTHON_DIR%\python.exe" "%PYTHON_DIR%\Scripts\pywin32_postinstall.py" -install -quiet >nul 2>&1
)

:: Verify installations
echo.
echo [INFO] Verifying installations...

set "VERIFY_FAIL=0"

"%PYTHON_DIR%\python.exe" -c "import psutil; print('[OK] psutil:', psutil.__version__)" 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] psutil
    set "VERIFY_FAIL=1"
)

"%PYTHON_DIR%\python.exe" -c "import requests; print('[OK] requests:', requests.__version__)" 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] requests
    set "VERIFY_FAIL=1"
)

"%PYTHON_DIR%\python.exe" -c "import win32api; print('[OK] pywin32')" 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] pywin32
    set "VERIFY_FAIL=1"
)

if "%VERIFY_FAIL%"=="1" (
    echo.
    echo [ERROR] Some packages failed to install
    pause
    exit /b 1
)

:: Clean up unnecessary files (reduce size)
echo.
echo [INFO] Cleaning up to reduce size...

:: Remove pip cache
rd /s /q "%PYTHON_DIR%\Lib\site-packages\pip" 2>nul

:: Remove test files
for /r "%PYTHON_DIR%" %%D in (test tests) do (
    if exist "%%D" rd /s /q "%%D" 2>nul
)

:: Remove documentation
for /r "%PYTHON_DIR%" %%D in (doc docs) do (
    if exist "%%D" rd /s /q "%%D" 2>nul
)

:: Remove __pycache__ (will be regenerated)
for /d /r "%PYTHON_DIR%" %%D in (__pycache__) do (
    if exist "%%D" rd /s /q "%%D" 2>nul
)

:: Remove .dist-info and .data folders (metadata)
for /d %%D in ("%PYTHON_DIR%\Lib\site-packages\*.dist-info") do (
    rd /s /q "%%D" 2>nul
)

:: Calculate final size
set "FOLDER_SIZE=0"
for /r "%PYTHON_DIR%" %%F in (*) do (
    set /a FOLDER_SIZE+=%%~zF
)
set /a FOLDER_SIZE_MB=%FOLDER_SIZE% / 1048576

echo [OK] Cleanup complete

:: Summary
echo.
echo ========================================================================
echo   Python 3.13 Bundle Created Successfully
echo ========================================================================
echo.
echo   Location:     %PYTHON_DIR%
echo   Size:         ~%FOLDER_SIZE_MB% MB
echo.
echo   Next steps:
echo   1. Copy the python313 folder into your installer package
echo   2. Place alongside install.bat, sentinel_core.py, etc.
echo   3. Distribute the complete package
echo.
echo ========================================================================
echo.

:: Clean up temp files
del "%GET_PIP%" 2>nul
del "%PYTHON_ZIP%" 2>nul
rd /s /q "%TEMP_DIR%" 2>nul

pause
