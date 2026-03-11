@echo off
setlocal enabledelayedexpansion

:: Change to script's directory (fixes "Run as Administrator" issue)
cd /d "%~dp0"

:: SentinelEdge Diagnostic Collector
:: version 1.4 - Added computer name and username to filename

set "STAMP=%DATE:~10,4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%"
set "STAMP=%STAMP: =0%"
set "DIAG_DIR=SentinelEdge_Diag_%COMPUTERNAME%_%USERNAME%_%STAMP%"
set "ZIP_FILE=SentinelEdge_Diag_%COMPUTERNAME%_%USERNAME%_%STAMP%.zip"

echo ============================================================
echo      SentinelEdge Agent - Diagnostic Collector
echo ============================================================
echo Computer: %COMPUTERNAME%
echo User: %USERNAME%
echo Working Directory: %CD%
echo.

:: Check for Administrative privileges
echo [1/5] Checking for Administrative privileges...
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Running with Administrative privileges.
) else (
    echo [!] This script requires Administrative privileges to collect all logs.
    echo [!] Attempting to elevate...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: Create temporary directory
echo [2/5] Creating temporary collection folder...
if not exist "%DIAG_DIR%" mkdir "%DIAG_DIR%"
if not exist "%DIAG_DIR%\logs" mkdir "%DIAG_DIR%\logs"

:: Collect Core Logs (Last 2 Days Only)
echo [3/5] Collecting Core Service logs (last 2 days)...
set "CORE_LOG_DIR=C:\ProgramData\SentinelEdge\logs"
if exist "%CORE_LOG_DIR%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$cutoff = (Get-Date).AddDays(-2); Get-ChildItem -Path '%CORE_LOG_DIR%' -Filter *.log -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $cutoff } | ForEach-Object { Copy-Item -Path $_.FullName -Destination '%DIAG_DIR%\logs\' -Force -ErrorAction SilentlyContinue }"
    echo [OK] Core logs collected.
) else (
    echo [SKIP] Core log directory not found.
)

:: Collect Helper Logs (Last 2 Days Only)
echo [4/5] Collecting Helper logs (last 2 days)...
set "HELPER_LOG_DIR=%APPDATA%\SentinelEdge"
if exist "%HELPER_LOG_DIR%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$cutoff = (Get-Date).AddDays(-2); Get-ChildItem -Path '%HELPER_LOG_DIR%' -Filter *.log -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $cutoff } | ForEach-Object { Copy-Item -Path $_.FullName -Destination '%DIAG_DIR%\logs\' -Force -ErrorAction SilentlyContinue }"
    echo [OK] Helper logs collected.
) else (
    echo [SKIP] Helper log directory not found.
)

:: Collect System Info
echo [5/5] Gathering system information and process status...
(
    echo SENTINELEDGE DIAGNOSTIC REPORT
    echo Generated: %DATE% %TIME%
    echo Computer Name: %COMPUTERNAME%
    echo Username: %USERNAME%
    echo Domain: %USERDOMAIN%
    echo Filtering: Logs modified in the last 48 hours only
    echo ============================================================
    echo.
    echo SYSTEM INFORMATION
    echo ------------------
    systeminfo 2>nul | findstr /B /C:"OS Name" /C:"OS Version" /C:"System Manufacturer" /C:"System Model" /C:"System Type" /C:"Total Physical Memory"
    echo.
    echo RUNNING PROCESSES (SentinelEdge)
    echo --------------------------------
    tasklist /FI "IMAGENAME eq sentinel*" 2>nul
    echo.
    echo NETWORK STATUS (Agent Ports)
    echo ----------------------------
    netstat -ano 2>nul | findstr "5050"
    echo.
    echo SERVICE STATUS
    echo --------------
    sc query SentinelEdgeCore 2>nul || echo SentinelEdgeCore service not found.
) > "%DIAG_DIR%\system_report.txt"

:: Zip the results
echo.
echo [FINAL] Packaging diagnostic data...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIAG_DIR%' -DestinationPath '%ZIP_FILE%' -Force -ErrorAction Stop"

if exist "%ZIP_FILE%" (
    echo.
    echo ============================================================
    echo SUCCESS: Diagnostic package created:
    echo %CD%\%ZIP_FILE%
    echo ============================================================
    echo.
    echo Opening folder...
    explorer /select,"%CD%\%ZIP_FILE%"
) else (
    echo [ERROR] Failed to create zip file.
    echo Press any key to view the collected files...
    pause >nul
    explorer "%DIAG_DIR%"
)

:: Cleanup
if exist "%ZIP_FILE%" (
    echo Cleaning up temporary files...
    rmdir /s /q "%DIAG_DIR%" 2>nul
)

echo.
pause
