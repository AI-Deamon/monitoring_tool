@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: SentinelEdge Agent Uninstaller
:: ============================================================================

cd /d "%~dp0"

:: ============================================================================
:: Check Administrator Privileges
:: ============================================================================
echo [INFO] Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Administrator privileges required.
    echo Right-click uninstall.bat and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo SentinelEdge Uninstaller
echo ============================================================================
echo.
echo This will remove:
echo   - Core service (SentinelEdgeCore)
echo   - Helper scheduled task (SentinelEdgeUserHelper)
echo   - Installation files (C:\Program Files\SentinelEdge)
echo.
echo Optionally remove:
echo   - Configuration and data (C:\ProgramData\SentinelEdge)
echo   - User helper data (%%APPDATA%%\SentinelEdge)
echo.

set /p "CONFIRM=Continue with uninstallation? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Uninstallation cancelled.
    exit /b 0
)

:: ============================================================================
:: Stop and Remove Core Service
:: ============================================================================
echo.
echo [INFO] Stopping Core service...

sc query SentinelEdgeCore >nul 2>&1
if %errorlevel% equ 0 (
    net stop SentinelEdgeCore >nul 2>&1
    timeout /t 3 /nobreak >nul
    
    :: Try NSSM removal
    if exist "C:\Program Files\SentinelEdge\nssm\win64\nssm.exe" (
        "C:\Program Files\SentinelEdge\nssm\win64\nssm.exe" remove SentinelEdgeCore confirm >nul 2>&1
    ) else (
        sc delete SentinelEdgeCore >nul 2>&1
    )
    
    echo [OK] Core service removed
) else (
    echo [INFO] Core service not found
)

:: ============================================================================
:: Stop and Remove Helper Task
:: ============================================================================
echo.
echo [INFO] Removing Helper task...

schtasks /query /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    schtasks /end /tn "SentinelEdgeUserHelper" >nul 2>&1
    schtasks /delete /tn "SentinelEdgeUserHelper" /f >nul 2>&1
    echo [OK] Helper task removed
) else (
    echo [INFO] Helper task not found
)

:: ============================================================================
:: Remove Installation Files
:: ============================================================================
echo.
echo [INFO] Removing installation files...

if exist "C:\Program Files\SentinelEdge\" (
    rmdir /s /q "C:\Program Files\SentinelEdge\" 2>nul
    if exist "C:\Program Files\SentinelEdge\" (
        echo [WARN] Could not remove all files (may be in use)
    ) else (
        echo [OK] Installation files removed
    )
) else (
    echo [INFO] Installation directory not found
)

:: ============================================================================
:: Remove Configuration and Data (Optional)
:: ============================================================================
echo.
set /p "REMOVE_DATA=Remove configuration and data? (Y/N): "
if /i "%REMOVE_DATA%"=="Y" (
    echo [INFO] Removing data directory...
    if exist "C:\ProgramData\SentinelEdge\" (
        rmdir /s /q "C:\ProgramData\SentinelEdge\" 2>nul
        echo [OK] Data directory removed
    )
)

:: ============================================================================
:: Remove User Data (Optional)
:: ============================================================================
echo.
set /p "REMOVE_USER_DATA=Remove user helper data? (Y/N): "
if /i "%REMOVE_USER_DATA%"=="Y" (
    echo [INFO] Removing user data...
    if exist "%APPDATA%\SentinelEdge\" (
        rmdir /s /q "%APPDATA%\SentinelEdge\" 2>nul
        echo [OK] User data removed
    )
)

:: ============================================================================
:: Summary
:: ============================================================================
echo.
echo ============================================================================
echo Uninstallation Complete
echo ============================================================================
echo.
echo Removed:
echo   [X] Core service
echo   [X] Helper task
echo   [X] Installation files
if /i "%REMOVE_DATA%"=="Y" (
    echo   [X] Configuration and data
)
if /i "%REMOVE_USER_DATA%"=="Y" (
    echo   [X] User helper data
)
echo.

pause