@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: WinDiagSvc (EXE) Uninstaller - Dev/Testing
:: Removes stealth-named EXE agent installation
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
    echo Right-click uninstall_exe.bat and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

set "SVC_NAME=WinDiagSvc"
set "TASK_NAME=SysHealthMon"
set "INSTALL_DIR=C:\Program Files\WinDiagSvc"
set "DATA_DIR=C:\ProgramData\WinDiagSvc"

echo.
echo ============================================================================
echo WinDiagSvc EXE Uninstaller
echo ============================================================================
echo.
echo This will remove:
echo   - Core service (%SVC_NAME%)
echo   - Helper scheduled task (%TASK_NAME%)
echo   - Installation files (%INSTALL_DIR%)
echo.
echo Optionally remove:
echo   - Configuration and data (%DATA_DIR%)
echo   - Per-user data (AppData\Roaming\WinDiagSvc and AppData\Local\WinDiagSvc)
echo.

set /p "CONFIRM=Continue with uninstallation? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Uninstallation cancelled.
    exit /b 0
)

:: ============================================================================
:: Step 1: Kill ALL related processes FIRST (before touching services)
:: ============================================================================
echo.
echo [STEP 1] Killing all agent processes...

:: Force kill every possible related process
taskkill /f /im windiag.exe >nul 2>&1
taskkill /f /im syshealth.exe >nul 2>&1
taskkill /f /im swapper.exe >nul 2>&1
taskkill /f /im nssm.exe >nul 2>&1
taskkill /f /im pythonw.exe >nul 2>&1

:: Also kill by window title pattern (catches child processes)
powershell -Command "Get-Process | Where-Object {$_.Path -like '*WinDiagSvc*' -or $_.Path -like '*windiag*' -or $_.Path -like '*syshealth*' -or $_.Path -like '*swapper*'} | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1

echo [OK] Processes terminated

:: ============================================================================
:: Step 2: Remove Core Service
:: ============================================================================
echo.
echo [STEP 2] Removing Core service...

sc query %SVC_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    net stop %SVC_NAME% >nul 2>&1

    :: NSSM removal
    if exist "%INSTALL_DIR%\nssm\win64\nssm.exe" (
        "%INSTALL_DIR%\nssm\win64\nssm.exe" stop %SVC_NAME% >nul 2>&1
        "%INSTALL_DIR%\nssm\win64\nssm.exe" remove %SVC_NAME% confirm >nul 2>&1
    )

    :: Force SC delete as fallback (works even if NSSM entry remains)
    sc delete %SVC_NAME% >nul 2>&1

    :: Kill nssm again (it may have respawned during remove)
    taskkill /f /im nssm.exe >nul 2>&1

    echo [OK] Core service removed
) else (
    echo [INFO] Core service not found — skipping
)

:: ============================================================================
:: Step 3: Remove Helper Task
:: ============================================================================
echo.
echo [STEP 3] Removing Helper task...

schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    schtasks /end /tn "%TASK_NAME%" >nul 2>&1
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
    echo [OK] Helper task removed
) else (
    echo [INFO] Helper task not found — skipping
)

:: Transient on-demand relaunch task created during auto-update swaps
:: (tools/swapper.py, core/service.py) — normally self-deletes, but a
:: crash mid-swap can leave it behind.
schtasks /query /tn "%TASK_NAME%_OnDemand" >nul 2>&1
if %errorlevel% equ 0 (
    schtasks /end /tn "%TASK_NAME%_OnDemand" >nul 2>&1
    schtasks /delete /tn "%TASK_NAME%_OnDemand" /f >nul 2>&1
    echo [OK] Leftover on-demand helper task removed
)

:: ============================================================================
:: Step 4: Remove Installation Files (with retry)
:: ============================================================================
echo.
echo [STEP 4] Removing installation files...

if exist "%INSTALL_DIR%\" (
    :: Final kill sweep before deletion
    taskkill /f /im windiag.exe >nul 2>&1
    taskkill /f /im syshealth.exe >nul 2>&1
    taskkill /f /im swapper.exe >nul 2>&1
    taskkill /f /im nssm.exe >nul 2>&1

    :: Wait for OS to release file handles
    echo          Waiting for file handles to release...
    timeout /t 5 /nobreak >nul

    :: Reset ACLs on install dir (remove deny-delete rules)
    icacls "%INSTALL_DIR%" /reset /t /q >nul 2>&1

    :: Attempt 1: rmdir
    rmdir /s /q "%INSTALL_DIR%\" 2>nul

    if exist "%INSTALL_DIR%\" (
        :: Attempt 2: Wait longer and retry
        echo          Retry 1 — waiting 5 more seconds...
        timeout /t 5 /nobreak >nul
        rmdir /s /q "%INSTALL_DIR%\" 2>nul
    )

    if exist "%INSTALL_DIR%\" (
        :: Attempt 3: PowerShell force removal
        echo          Retry 2 — using PowerShell...
        powershell -Command "Remove-Item -Path '%INSTALL_DIR%' -Recurse -Force -ErrorAction SilentlyContinue"
    )

    if exist "%INSTALL_DIR%\" (
        :: Attempt 4: Nuclear — delete files individually, then directory
        echo          Retry 3 — deleting files individually...
        powershell -Command "Get-ChildItem '%INSTALL_DIR%' -Recurse -File | ForEach-Object { try { $_.Delete() } catch {} }; Get-ChildItem '%INSTALL_DIR%' -Recurse -Directory | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { try { $_.Delete() } catch {} }; try { [System.IO.Directory]::Delete('%INSTALL_DIR%', $true) } catch {}"
    )

    if exist "%INSTALL_DIR%\" (
        echo [WARN] Some files still locked. Scheduling delayed delete for next reboot...
        set "MOVEFILE_PS1=%TEMP%\wds_uninstall_movefile.ps1"
        (
        echo $sig = @'
        echo using System;
        echo using System.Runtime.InteropServices;
        echo public class WdsNative {
        echo     [DllImport^("kernel32.dll", SetLastError = true, CharSet = CharSet.Auto^)]
        echo     public static extern bool MoveFileEx^(string lpExistingFileName, string lpNewFileName, int dwFlags^);
        echo }
        echo '@
        echo Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue
        echo Get-ChildItem -Path "%INSTALL_DIR%" -Recurse -File -ErrorAction SilentlyContinue ^| ForEach-Object {
        echo     [WdsNative]::MoveFileEx^($_.FullName, $null, 4^) ^| Out-Null
        echo }
        ) > "!MOVEFILE_PS1!"
        powershell -NoProfile -ExecutionPolicy Bypass -File "!MOVEFILE_PS1!" >nul 2>&1
        del /f /q "!MOVEFILE_PS1!" >nul 2>&1
        echo        Locked files registered for deletion on next reboot ^(via MoveFileEx^)
        echo        Manual fallback: delete %INSTALL_DIR% after reboot if anything remains
    ) else (
        echo [OK] Installation files removed
    )
) else (
    echo [INFO] Installation directory not found
)

:: ============================================================================
:: Step 5: Remove Data (Optional)
:: ============================================================================
echo.
set /p "REMOVE_DATA=Remove configuration, data and logs? (Y/N): "
if /i "%REMOVE_DATA%"=="Y" (
    echo [INFO] Removing data directory...
    if exist "%DATA_DIR%\" (
        :: Reset ACLs first (install_exe.bat sets deny-delete)
        icacls "%DATA_DIR%" /reset /t /q >nul 2>&1
        timeout /t 2 /nobreak >nul
        rmdir /s /q "%DATA_DIR%\" 2>nul

        if exist "%DATA_DIR%\" (
            :: PowerShell fallback
            powershell -Command "Remove-Item -Path '%DATA_DIR%' -Recurse -Force -ErrorAction SilentlyContinue"
        )

        if exist "%DATA_DIR%\" (
            echo [WARN] Could not remove data directory
        ) else (
            echo [OK] Data directory removed
        )
    ) else (
        echo [INFO] Data directory not found
    )

    :: Per-user data: Helper writes helper_state.json/helper.log to
    :: AppData\Roaming\WinDiagSvc (helper/config.py), and Core's writable
    :: data dir falls back to AppData\Local\WinDiagSvc when ProgramData
    :: isn't writable (core/config.py _get_writable_data_dir).
    echo [INFO] Checking per-user data directories...
    for /d %%U in ("C:\Users\*") do (
        if exist "%%U\AppData\Roaming\WinDiagSvc\" (
            echo   - Cleaning Roaming AppData for %%~nU
            icacls "%%U\AppData\Roaming\WinDiagSvc" /reset /t /q >nul 2>&1
            rmdir /s /q "%%U\AppData\Roaming\WinDiagSvc\" 2>nul
            if exist "%%U\AppData\Roaming\WinDiagSvc\" (
                powershell -Command "Remove-Item -Path '%%U\AppData\Roaming\WinDiagSvc' -Recurse -Force -ErrorAction SilentlyContinue"
            )
        )
        if exist "%%U\AppData\Local\WinDiagSvc\" (
            echo   - Cleaning Local AppData for %%~nU
            icacls "%%U\AppData\Local\WinDiagSvc" /reset /t /q >nul 2>&1
            rmdir /s /q "%%U\AppData\Local\WinDiagSvc\" 2>nul
            if exist "%%U\AppData\Local\WinDiagSvc\" (
                powershell -Command "Remove-Item -Path '%%U\AppData\Local\WinDiagSvc' -Recurse -Force -ErrorAction SilentlyContinue"
            )
        )
    )
    echo [OK] Per-user data directories checked
) else (
    echo [INFO] Data preserved at %DATA_DIR%
)

:: ============================================================================
:: Step 6: Also clean legacy SentinelEdge if present
:: ============================================================================
echo.
echo [STEP 6] Checking for legacy installation...

set "LEGACY_FOUND=0"
sc query SentinelEdgeCore >nul 2>&1
if %errorlevel% equ 0 set "LEGACY_FOUND=1"
if exist "C:\Program Files\SentinelEdge\" set "LEGACY_FOUND=1"
if exist "C:\ProgramData\SentinelEdge\" set "LEGACY_FOUND=1"
for /d %%U in ("C:\Users\*") do (
    if exist "%%U\AppData\Roaming\SentinelEdge\" set "LEGACY_FOUND=1"
)

if "%LEGACY_FOUND%"=="1" (
    set /p "REMOVE_LEGACY=Legacy SentinelEdge installation found. Remove it too? (Y/N): "
    if /i "!REMOVE_LEGACY!"=="Y" (
        echo [INFO] Removing legacy installation...
        net stop SentinelEdgeCore >nul 2>&1
        schtasks /end /tn "SentinelEdgeUserHelper" >nul 2>&1
        schtasks /delete /tn "SentinelEdgeUserHelper" /f >nul 2>&1
        taskkill /f /im pythonw.exe >nul 2>&1
        taskkill /f /im python.exe >nul 2>&1

        if exist "C:\Program Files\SentinelEdge\nssm\win64\nssm.exe" (
            "C:\Program Files\SentinelEdge\nssm\win64\nssm.exe" remove SentinelEdgeCore confirm >nul 2>&1
        ) else (
            sc delete SentinelEdgeCore >nul 2>&1
        )

        rmdir /s /q "C:\Program Files\SentinelEdge\" 2>nul
        if exist "C:\Program Files\SentinelEdge\" (
            powershell -Command "Remove-Item -Path 'C:\Program Files\SentinelEdge' -Recurse -Force -ErrorAction SilentlyContinue"
        )

        rmdir /s /q "C:\ProgramData\SentinelEdge\" 2>nul
        if exist "C:\ProgramData\SentinelEdge\" (
            powershell -Command "Remove-Item -Path 'C:\ProgramData\SentinelEdge' -Recurse -Force -ErrorAction SilentlyContinue"
        )

        for /d %%U in ("C:\Users\*") do (
            if exist "%%U\AppData\Roaming\SentinelEdge\" (
                echo   - Cleaning AppData for %%~nU
                icacls "%%U\AppData\Roaming\SentinelEdge" /reset /t /q >nul 2>&1
                rmdir /s /q "%%U\AppData\Roaming\SentinelEdge\" 2>nul
                if exist "%%U\AppData\Roaming\SentinelEdge\" (
                    powershell -Command "Remove-Item -Path '%%U\AppData\Roaming\SentinelEdge' -Recurse -Force -ErrorAction SilentlyContinue"
                )
            )
        )
        echo [OK] Legacy installation removed
    )
) else (
    echo [INFO] No legacy installation found
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
echo   [X] Core service ^(%SVC_NAME%^)
echo   [X] Helper task ^(%TASK_NAME%^)
echo   [X] Installation files
if /i "%REMOVE_DATA%"=="Y" (
    echo   [X] Configuration and data
) else (
    echo   [ ] Configuration and data ^(preserved^)
)
echo.

pause
