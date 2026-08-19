@echo off
setlocal EnableDelayedExpansion

:: Quick restart helper/core across EXE and legacy installs.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Run as Administrator!
    pause
    exit /b 1
)

set "CORE_SVC=SentinelEdgeCore"
set "HELPER_TASK=SentinelEdgeUserHelper"
set "HELPER_EXE=sentinel_helper.exe"
set "INSTALL_DIR=C:\Program Files\SentinelEdge"

:: Prefer EXE deployment if present
sc query WinDiagSvc >nul 2>&1
if %errorlevel%==0 (
    set "CORE_SVC=WinDiagSvc"
    set "HELPER_TASK=SysHealthMon"
    set "HELPER_EXE=syshealth.exe"
    set "INSTALL_DIR=C:\Program Files\WinDiagSvc"
)

echo Restarting services...
echo Core Service: %CORE_SVC%
echo Helper Task : %HELPER_TASK%
echo.

echo Stopping core service...
net stop %CORE_SVC% >nul 2>&1
timeout /t 2 /nobreak >nul

echo Stopping helper task...
schtasks /end /tn "%HELPER_TASK%" >nul 2>&1
schtasks /end /tn "SysHealthMon" >nul 2>&1
schtasks /end /tn "SentinelEdgeUserHelper" >nul 2>&1
timeout /t 1 /nobreak >nul

echo Killing stale helper processes...
taskkill /f /im "%HELPER_EXE%" >nul 2>&1
taskkill /f /im "syshealth.exe" >nul 2>&1
taskkill /f /im "sentinel_helper.exe" >nul 2>&1

echo Killing orphaned PowerShell processes from inventory collection...
taskkill /f /im "powershell.exe" /fi "WINDOWTITLE eq SentinelEdge*" >nul 2>&1

echo Starting core service...
net start %CORE_SVC% >nul 2>&1
timeout /t 3 /nobreak >nul

echo Starting helper task...
set "HELPER_STARTED=0"
schtasks /run /tn "%HELPER_TASK%" >nul 2>&1
if %errorlevel% equ 0 set "HELPER_STARTED=1"

if "!HELPER_STARTED!"=="0" (
    echo Primary helper task failed, trying fallbacks...
    schtasks /run /tn "SysHealthMon" >nul 2>&1
    if !errorlevel! equ 0 set "HELPER_STARTED=1"
    schtasks /run /tn "SentinelEdgeUserHelper" >nul 2>&1
    if !errorlevel! equ 0 set "HELPER_STARTED=1"
)

if "!HELPER_STARTED!"=="0" (
    echo schtasks /run failed, trying Start-ScheduledTask...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-ScheduledTask -TaskName '%HELPER_TASK%'" >nul 2>&1
    if !errorlevel! equ 0 set "HELPER_STARTED=1"
)

if "!HELPER_STARTED!"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-ScheduledTask -TaskName 'SysHealthMon'" >nul 2>&1
    if !errorlevel! equ 0 set "HELPER_STARTED=1"
)

if "!HELPER_STARTED!"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-ScheduledTask -TaskName 'SentinelEdgeUserHelper'" >nul 2>&1
    if !errorlevel! equ 0 set "HELPER_STARTED=1"
)

if "!HELPER_STARTED!"=="0" (
    if exist "%INSTALL_DIR%\%HELPER_EXE%" (
        echo Task API start failed, launching helper directly for this session...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%INSTALL_DIR%\%HELPER_EXE%' -WorkingDirectory '%INSTALL_DIR%' -WindowStyle Hidden" >nul 2>&1
        if !errorlevel! equ 0 set "HELPER_STARTED=1"
    )
)

if "!HELPER_STARTED!"=="1" (
    echo Helper start requested successfully.
) else (
    echo Helper start failed. Check Task Scheduler and helper logs.
)

echo.
echo Done.
timeout /t 2 >nul
endlocal
