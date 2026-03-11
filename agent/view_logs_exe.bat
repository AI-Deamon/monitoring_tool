@echo off
setlocal

:: ============================================================================
:: WinDiagSvc (EXE) Log Viewer - Dev/Testing
:: ============================================================================

set "DATA_DIR=C:\ProgramData\WinDiagSvc"
set "LEGACY_DIR=C:\ProgramData\SentinelEdge"

:: Auto-detect data directory
if not exist "%DATA_DIR%\logs" (
    if exist "%LEGACY_DIR%\logs" (
        echo [INFO] Using legacy data directory
        set "DATA_DIR=%LEGACY_DIR%"
    )
)

:menu
cls
echo ============================================================================
echo WinDiagSvc Log Viewer
echo ============================================================================
echo Data: %DATA_DIR%
echo.
echo 1. Core Service Log       (last 50 lines)
echo 2. Core Error Log         (last 30 lines)
echo 3. Core NSSM stdout       (last 30 lines)
echo 4. Helper Log             (last 50 lines)
echo 5. Live tail Core log     (Ctrl+C to stop)
echo 6. Live tail Helper log   (Ctrl+C to stop)
echo 7. Service Status
echo 8. Open logs folder
echo 9. Exit
echo.
set /p choice="Select option [1-9]: "

if "%choice%"=="1" goto core_log
if "%choice%"=="2" goto core_error
if "%choice%"=="3" goto core_nssm
if "%choice%"=="4" goto helper_log
if "%choice%"=="5" goto tail_core
if "%choice%"=="6" goto tail_helper
if "%choice%"=="7" goto svc_status
if "%choice%"=="8" goto open_folder
if "%choice%"=="9" exit /b
goto menu

:core_log
cls
echo === Core Service Log (last 50 lines) ===
echo.
powershell -Command "if (Test-Path '%DATA_DIR%\logs\core.log') { Get-Content '%DATA_DIR%\logs\core.log' -Tail 50 } else { Write-Host 'Log file not found at %DATA_DIR%\logs\core.log' }"
echo.
pause
goto menu

:core_error
cls
echo === Core Error Log (last 30 lines) ===
echo.
powershell -Command "$f = '%DATA_DIR%\logs\core_stderr.log'; if (Test-Path $f) { Get-Content $f -Tail 30 } else { Write-Host 'No stderr log found (good - no crashes)' }"
echo.
pause
goto menu

:core_nssm
cls
echo === Core NSSM stdout (last 30 lines) ===
echo.
powershell -Command "$f = '%DATA_DIR%\logs\core_stdout.log'; if (Test-Path $f) { Get-Content $f -Tail 30 } else { Write-Host 'No NSSM stdout log found' }"
echo.
pause
goto menu

:helper_log
cls
echo === Helper Log (last 50 lines) ===
echo.
:: Helper logs can be in APPDATA or DATA_DIR depending on context
powershell -Command "$paths = @('%APPDATA%\SentinelEdge\helper.log', '%APPDATA%\WinDiagSvc\helper.log', '%DATA_DIR%\logs\helper.log'); $found = $false; foreach ($p in $paths) { if (Test-Path $p) { Write-Host \"Source: $p\" -ForegroundColor Cyan; Write-Host ''; Get-Content $p -Tail 50; $found = $true; break } }; if (-not $found) { Write-Host 'Helper log not found. Checked:'; $paths | ForEach-Object { Write-Host \"  - $_\" } }"
echo.
pause
goto menu

:tail_core
cls
echo === Live Core Log (Ctrl+C to stop) ===
echo.
if exist "%DATA_DIR%\logs\core.log" (
    powershell -Command "Get-Content '%DATA_DIR%\logs\core.log' -Wait -Tail 10"
) else (
    echo Log file not found at %DATA_DIR%\logs\core.log
    pause
)
goto menu

:tail_helper
cls
echo === Live Helper Log (Ctrl+C to stop) ===
echo.
powershell -Command "$paths = @('%APPDATA%\SentinelEdge\helper.log', '%APPDATA%\WinDiagSvc\helper.log', '%DATA_DIR%\logs\helper.log'); foreach ($p in $paths) { if (Test-Path $p) { Write-Host \"Tailing: $p\" -ForegroundColor Cyan; Get-Content $p -Wait -Tail 1000; exit } }; Write-Host 'Helper log not found'"
pause
goto menu

:svc_status
cls
echo === Service and Task Status ===
echo.

echo --- Core Service (WinDiagSvc) ---
sc query WinDiagSvc 2>nul
if %errorlevel% neq 0 (
    echo   [NOT INSTALLED]
    echo.
    echo --- Legacy Core (SentinelEdgeCore) ---
    sc query SentinelEdgeCore 2>nul
    if %errorlevel% neq 0 echo   [NOT INSTALLED]
)
echo.

echo --- Helper Task (SysHealthMon) ---
schtasks /query /tn "SysHealthMon" /fo LIST 2>nul
if %errorlevel% neq 0 (
    echo   [NOT INSTALLED]
    echo.
    echo --- Legacy Helper (SentinelEdgeUserHelper) ---
    schtasks /query /tn "SentinelEdgeUserHelper" /fo LIST 2>nul
    if %errorlevel% neq 0 echo   [NOT INSTALLED]
)
echo.

echo --- Running Processes ---
powershell -Command "Get-Process -Name windiag,syshealth -ErrorAction SilentlyContinue | Format-Table Name,Id,CPU,WorkingSet64 -AutoSize; if (-not $?) { Write-Host '  No agent processes running' }"
echo.

echo --- Agent Identity ---
if exist "%DATA_DIR%\agent_id" (
    powershell -Command "Write-Host '  Agent ID: ' -NoNewline; Get-Content '%DATA_DIR%\agent_id'"
) else (
    echo   Agent ID file not found
)
echo.

echo --- Config Path ---
if exist "%DATA_DIR%\config.json" (
    echo   %DATA_DIR%\config.json
) else if exist "C:\ProgramData\SentinelEdge\config.json" (
    echo   C:\ProgramData\SentinelEdge\config.json (legacy)
) else (
    echo   No config.json found
)
echo.
pause
goto menu

:open_folder
if exist "%DATA_DIR%\logs" (
    explorer "%DATA_DIR%\logs"
) else (
    echo Logs folder not found at %DATA_DIR%\logs
    pause
)
goto menu
