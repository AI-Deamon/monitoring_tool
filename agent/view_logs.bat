@echo off
setlocal

set "DATA_DIR=C:\ProgramData\SentinelEdge"

:menu
cls
echo ============================================================================
echo SentinelEdge Log Viewer
echo ============================================================================
echo.
echo 1. Core Service Log (last 30 lines)
echo 2. Core Error Log (last 30 lines)
echo 3. Helper Log (last 30 lines)
echo 4. Live tail Core log (Ctrl+C to stop)
echo 5. Live tail Helper log (Ctrl+C to stop)
echo 6. Open logs folder
echo 7. Exit
echo.
set /p choice="Select option [1-7]: "

if "%choice%"=="1" goto core_log
if "%choice%"=="2" goto core_error
if "%choice%"=="3" goto helper_log
if "%choice%"=="4" goto tail_core
if "%choice%"=="5" goto tail_helper
if "%choice%"=="6" goto open_folder
if "%choice%"=="7" exit /b
goto menu

:core_log
cls
echo === Core Service Log (last 30 lines) ===
echo.
powershell -Command "if (Test-Path '%DATA_DIR%\logs\core.log') { Get-Content '%DATA_DIR%\logs\core.log' -Tail 30 } else { Write-Host 'Log file not found' }"
echo.
pause
goto menu

:core_error
cls
echo === Core Error Log (last 30 lines) ===
echo.
powershell -Command "if (Test-Path '%DATA_DIR%\logs\core_stderr.log') { Get-Content '%DATA_DIR%\logs\core_stderr.log' -Tail 30 } else { Write-Host 'No errors logged' }"
echo.
pause
goto menu

:helper_log
cls
echo === Helper Log (last 30 lines) ===
echo.
powershell -Command "if (Test-Path '%APPDATA%\SentinelEdge\helper.log') { Get-Content '%APPDATA%\SentinelEdge\helper.log' -Tail 50 } else { Write-Host 'Log file not found' }"
echo.
pause
goto menu

:tail_core
cls
echo === Live Core Log (Ctrl+C to stop) ===
echo.
powershell -Command "Get-Content '%DATA_DIR%\logs\core.log' -Wait -Tail 10"
goto menu

:tail_helper
cls
echo === Live Helper Log (Ctrl+C to stop) ===
echo.
powershell -Command "Get-Content '%APPDATA%\SentinelEdge\helper.log' -Wait -Tail 100"
goto menu

:open_folder
explorer "%DATA_DIR%\logs"
goto menu
