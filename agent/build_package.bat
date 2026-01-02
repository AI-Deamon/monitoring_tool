@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: SentinelEdge Agent - Deployment Package Builder
:: ============================================================================
:: Creates a ready-to-deploy ZIP package with all required files
:: ============================================================================

cd /d "%~dp0"

echo.
echo ========================================================================
echo   SentinelEdge Agent - Deployment Package Builder
echo ========================================================================
echo.

:: Set version
set "VERSION=2.1.0"
set "BUILD_DATE=%date:~10,4%%date:~4,2%%date:~7,2%"
set "PACKAGE_NAME=SentinelEdge-Agent-%VERSION%"
set "OUTPUT_DIR=..\deploy"
set "TEMP_PKG=%OUTPUT_DIR%\%PACKAGE_NAME%"

echo [INFO] Version: %VERSION%
echo [INFO] Package: %PACKAGE_NAME%
echo.

:: ============================================================================
:: STEP 1: Check Required Files
:: ============================================================================
echo [INFO] Checking required files...

set "MISSING=0"

if not exist "install.bat" (
    echo [FAIL] Missing: install.bat
    set "MISSING=1"
)
if not exist "uninstall.bat" (
    echo [FAIL] Missing: uninstall.bat
    set "MISSING=1"
)
if not exist "update.bat" (
    echo [FAIL] Missing: update.bat
    set "MISSING=1"
)
if not exist "sentinel_core.py" (
    echo [FAIL] Missing: sentinel_core.py
    set "MISSING=1"
)
if not exist "sentinel_helper.py" (
    echo [FAIL] Missing: sentinel_helper.py
    set "MISSING=1"
)
if not exist "core\service.py" (
    echo [FAIL] Missing: core\service.py
    set "MISSING=1"
)
if not exist "helper\main.py" (
    echo [FAIL] Missing: helper\main.py
    set "MISSING=1"
)
if not exist "nssm\win64\nssm.exe" (
    echo [FAIL] Missing: nssm\win64\nssm.exe
    set "MISSING=1"
)

if "%MISSING%"=="1" (
    echo.
    echo [ERROR] Some required files are missing!
    pause
    exit /b 1
)

echo [OK] All required files present
echo.

:: ============================================================================
:: STEP 2: Check Python Bundle
:: ============================================================================
echo [INFO] Checking Python bundle...

if not exist "python313" (
    echo.
    echo [WARN] Python 3.13 bundle not found!
    echo [INFO] Run create_python_bundle.bat first to create it.
    echo.
    choice /m "Continue without Python bundle (users will need to run bundle script)?"
    if errorlevel 2 exit /b 1
) else (
    if not exist "python313\python.exe" (
        echo [ERROR] Python bundle incomplete - python.exe missing
        pause
        exit /b 1
    )
    echo [OK] Python 3.13 bundle found
)
echo.

:: ============================================================================
:: STEP 3: Clean and Create Output Directory
:: ============================================================================
echo [INFO] Preparing output directory...

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if exist "%TEMP_PKG%" rmdir /s /q "%TEMP_PKG%"
mkdir "%TEMP_PKG%"

echo [OK] Output directory: %OUTPUT_DIR%
echo.

:: ============================================================================
:: STEP 4: Copy Files to Package
:: ============================================================================
echo [INFO] Copying files to package...

:: Main scripts
echo   - Main scripts...
copy /y "install.bat" "%TEMP_PKG%\" >nul
copy /y "uninstall.bat" "%TEMP_PKG%\" >nul
copy /y "update.bat" "%TEMP_PKG%\" >nul
copy /y "view_logs.bat" "%TEMP_PKG%\" >nul
copy /y "quick_restart.bat" "%TEMP_PKG%\" >nul
copy /y "harden_install.py" "%TEMP_PKG%\" >nul

:: Entry point scripts
echo   - Entry points...
copy /y "sentinel_core.py" "%TEMP_PKG%\" >nul
copy /y "sentinel_helper.py" "%TEMP_PKG%\" >nul

:: Core module
echo   - Core module...
mkdir "%TEMP_PKG%\core" >nul 2>&1
xcopy /s /i /y /q "core\*.py" "%TEMP_PKG%\core\" >nul

:: Helper module
echo   - Helper module...
mkdir "%TEMP_PKG%\helper" >nul 2>&1
xcopy /s /i /y /q "helper\*.py" "%TEMP_PKG%\helper\" >nul

:: NSSM (service manager)
echo   - NSSM service manager...
xcopy /s /i /y /q "nssm\*" "%TEMP_PKG%\nssm\" >nul

:: Python bundle (if exists)
if exist "python313" (
    echo   - Python 3.13 bundle (this may take a moment)...
    xcopy /s /i /y /q "python313\*" "%TEMP_PKG%\python313\" >nul
)

:: Documentation
echo   - Documentation...
if exist "README.md" copy /y "README.md" "%TEMP_PKG%\" >nul
if exist "INSTALL_INSTRUCTIONS.md" copy /y "INSTALL_INSTRUCTIONS.md" "%TEMP_PKG%\" >nul

echo [OK] Files copied
echo.

:: ============================================================================
:: STEP 5: Remove Unnecessary Files
:: ============================================================================
echo [INFO] Cleaning package...

:: Remove __pycache__ directories
for /d /r "%TEMP_PKG%" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d" 2>nul
)

:: Remove .pyc files (we'll compile on install)
del /s /q "%TEMP_PKG%\*.pyc" 2>nul

:: Remove test files
del /s /q "%TEMP_PKG%\test_*.py" 2>nul

:: Remove .git directory if present
if exist "%TEMP_PKG%\.git" rmdir /s /q "%TEMP_PKG%\.git"

echo [OK] Package cleaned
echo.

:: ============================================================================
:: STEP 6: Create VERSION File
:: ============================================================================
echo [INFO] Creating version file...

(
echo SentinelEdge Agent
echo Version: %VERSION%
echo Build Date: %BUILD_DATE%
echo.
echo Installation:
echo   1. Extract all files
echo   2. Right-click install.bat, Run as Administrator
echo   3. Enter server URL and registration secret
echo.
echo Requirements:
echo   - Windows 10/11 (x64^)
echo   - Administrator privileges
echo   - Network access to server
) > "%TEMP_PKG%\VERSION.txt"

echo [OK] Version file created
echo.

:: ============================================================================
:: STEP 7: Create ZIP Package
:: ============================================================================
echo [INFO] Creating ZIP package...

:: Check for PowerShell zip capability
powershell -Command "Get-Command Compress-Archive" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] PowerShell Compress-Archive not available
    echo [INFO] Package folder ready at: %TEMP_PKG%
    goto :done
)

:: Create ZIP
if exist "%OUTPUT_DIR%\%PACKAGE_NAME%.zip" del /q "%OUTPUT_DIR%\%PACKAGE_NAME%.zip"
powershell -Command "Compress-Archive -Path '%TEMP_PKG%\*' -DestinationPath '%OUTPUT_DIR%\%PACKAGE_NAME%.zip' -Force"

if %errorlevel% equ 0 (
    echo [OK] ZIP package created: %OUTPUT_DIR%\%PACKAGE_NAME%.zip
) else (
    echo [WARN] ZIP creation failed, folder package available
)

:: Calculate size
for %%A in ("%OUTPUT_DIR%\%PACKAGE_NAME%.zip") do set "ZIP_SIZE=%%~zA"
set /a ZIP_SIZE_MB=%ZIP_SIZE% / 1048576

echo.

:done
:: ============================================================================
:: STEP 8: Summary
:: ============================================================================
echo ========================================================================
echo   Deployment Package Ready!
echo ========================================================================
echo.
echo   Package Name:      %PACKAGE_NAME%
echo   Package Location:  %OUTPUT_DIR%\
if exist "%OUTPUT_DIR%\%PACKAGE_NAME%.zip" (
    echo   ZIP File:          %PACKAGE_NAME%.zip (%ZIP_SIZE_MB% MB^)
)
echo   Folder:            %PACKAGE_NAME%\
echo.
echo   Contents:
echo     - install.bat      (Main installer^)
echo     - uninstall.bat    (Clean removal^)
echo     - update.bat       (In-place update^)
echo     - sentinel_core.py (Core service entry^)
echo     - sentinel_helper.py (Helper entry^)
echo     - core\           (Core module^)
echo     - helper\         (Helper module^)
echo     - nssm\           (Service manager^)
if exist "%TEMP_PKG%\python313" (
    echo     - python313\      (Bundled Python 3.13^)
)
echo.
echo ========================================================================
echo   Deployment Instructions
echo ========================================================================
echo.
echo   1. Copy %PACKAGE_NAME%.zip to target Windows machine
echo   2. Extract to a temporary folder
echo   3. Right-click install.bat, select "Run as administrator"
echo   4. Enter server URL: http://YOUR_SERVER:5050
echo   5. Enter registration secret from admin panel
echo.
echo ========================================================================
echo.
pause
