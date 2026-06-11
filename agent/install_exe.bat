@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: WinDiagSvc Agent Installer - Standalone EXE Edition
:: ============================================================================
:: NO PYTHON REQUIRED - Ships pre-built executables
:: Stealth service names for tamper resistance
:: ============================================================================

cd /d "%~dp0"

echo.
echo ========================================================================
echo   System Diagnostics Installer v1.0
echo   Standalone Edition
echo ========================================================================
echo.

:: ============================================================================
:: STEP 1: Check Administrator Privileges
:: ============================================================================
echo [INFO] Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Administrator privileges required.
    echo Right-click install_exe.bat and select "Run as administrator"
    echo.
    pause
    exit /b 1
)
echo [OK] Administrator privileges confirmed

:: ============================================================================
:: STEP 2: Define Installation Paths (Stealth Names)
:: ============================================================================
set "INSTALL_DIR=C:\Program Files\WinDiagSvc"
set "DATA_DIR=C:\ProgramData\WinDiagSvc"
set "LOGS_DIR=%DATA_DIR%\logs"
set "STATE_DIR=%DATA_DIR%\state"
set "BUFFER_DIR=%DATA_DIR%\buffer"
set "CONFIG_FILE=%DATA_DIR%\config.json"
set "AGENT_ID_FILE=%DATA_DIR%\agent_id"

:: Stealth service/task names
set "CORE_SVC=WinDiagSvc"
set "CORE_DISPLAY=Windows Diagnostics Service"
set "CORE_EXE=windiag.exe"
set "HELPER_TASK=SysHealthMon"
set "HELPER_EXE=syshealth.exe"

:: Old names (for cleanup during upgrade)
set "OLD_CORE_SVC=SentinelEdgeCore"
set "OLD_HELPER_TASK=SentinelEdgeUserHelper"
set "OLD_INSTALL_DIR=C:\Program Files\SentinelEdge"
set "OLD_DATA_DIR=C:\ProgramData\SentinelEdge"

echo [INFO] Installation: %INSTALL_DIR%
echo [INFO] Data:         %DATA_DIR%
echo [INFO] Mode:         Standalone EXE (no Python needed)

:: ============================================================================
:: STEP 3: Verify EXE Files Exist
:: ============================================================================
echo.
echo [INFO] Verifying installer files...

if not exist "%CORE_EXE%" (
    echo.
    echo [ERROR] %CORE_EXE% not found!
    echo [ERROR] Expected in the same directory as this installer.
    echo.
    echo Please ensure both %CORE_EXE% and %HELPER_EXE% are present.
    echo.
    pause
    exit /b 1
)

if not exist "%HELPER_EXE%" (
    echo.
    echo [ERROR] %HELPER_EXE% not found!
    echo [ERROR] Expected in the same directory as this installer.
    echo.
    pause
    exit /b 1
)

if not exist "nssm\win64\nssm.exe" (
    echo.
    echo [ERROR] NSSM not found at nssm\win64\nssm.exe
    echo [ERROR] The installer package may be incomplete.
    echo.
    pause
    exit /b 1
)

if not exist "VERSION.txt" (
    echo.
    echo [ERROR] VERSION.txt not found in installer package
    echo [ERROR] Required to stamp the installed agent version.
    echo.
    pause
    exit /b 1
)

echo [OK] All installer files verified

:: ============================================================================
:: STEP 4: Get Server Configuration
:: ============================================================================
echo.
echo ========================================================================
echo   Server Configuration
echo ========================================================================
set "SERVER_URL=http://192.168.1.101:5050"
set /p "SERVER_URL=Enter server URL [%SERVER_URL%]: "
echo [INFO] Server URL: %SERVER_URL%

set "REGISTRATION_SECRET="
set /p "REGISTRATION_SECRET=Enter registration secret (from admin): "
if "%REGISTRATION_SECRET%"=="" (
    echo [WARN] No registration secret - registration may fail
) else (
    echo [OK] Registration secret configured
)

:: ============================================================================
:: STEP 5: Stop and Remove Old Installation (Both Old + New Names)
:: ============================================================================
echo.
echo [INFO] Checking for existing installations...

:: --- Remove NEW stealth service (if upgrading) ---
sc query %CORE_SVC% >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Stopping existing %CORE_SVC% service...
    net stop %CORE_SVC% >nul 2>&1
    timeout /t 3 /nobreak >nul

    :: Force stop if still running
    sc query %CORE_SVC% | findstr "RUNNING" >nul 2>&1
    if !errorlevel! equ 0 (
        taskkill /f /fi "SERVICES eq %CORE_SVC%" >nul 2>&1
        timeout /t 2 /nobreak >nul
    )

    :: Remove via NSSM if exists
    if exist "%INSTALL_DIR%\nssm\win64\nssm.exe" (
        "%INSTALL_DIR%\nssm\win64\nssm.exe" remove %CORE_SVC% confirm >nul 2>&1
    )
    sc delete %CORE_SVC% >nul 2>&1
    echo [OK] Existing stealth service removed
)

:: --- Remove OLD SentinelEdge service (if upgrading from Python version) ---
sc query %OLD_CORE_SVC% >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Removing legacy %OLD_CORE_SVC% service...
    net stop %OLD_CORE_SVC% >nul 2>&1
    timeout /t 3 /nobreak >nul

    sc query %OLD_CORE_SVC% | findstr "RUNNING" >nul 2>&1
    if !errorlevel! equ 0 (
        taskkill /f /fi "SERVICES eq %OLD_CORE_SVC%" >nul 2>&1
        timeout /t 2 /nobreak >nul
    )

    if exist "%OLD_INSTALL_DIR%\nssm\win64\nssm.exe" (
        "%OLD_INSTALL_DIR%\nssm\win64\nssm.exe" remove %OLD_CORE_SVC% confirm >nul 2>&1
    )
    sc delete %OLD_CORE_SVC% >nul 2>&1
    echo [OK] Legacy service removed
)

:: --- Remove NEW helper task ---
schtasks /query /tn "%HELPER_TASK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Removing existing %HELPER_TASK% task...
    schtasks /end /tn "%HELPER_TASK%" >nul 2>&1
    schtasks /delete /tn "%HELPER_TASK%" /f >nul 2>&1
)

:: --- Remove OLD helper task ---
schtasks /query /tn "%OLD_HELPER_TASK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Removing legacy %OLD_HELPER_TASK% task...
    schtasks /end /tn "%OLD_HELPER_TASK%" >nul 2>&1
    schtasks /delete /tn "%OLD_HELPER_TASK%" /f >nul 2>&1
)

:: --- Kill any running EXE processes ---
taskkill /f /im "%CORE_EXE%" >nul 2>&1
taskkill /f /im "%HELPER_EXE%" >nul 2>&1
:: Also kill old Python-based agents
taskkill /f /im pythonw.exe /fi "MODULES eq sentinel" >nul 2>&1
taskkill /f /im python.exe /fi "MODULES eq sentinel" >nul 2>&1
timeout /t 2 /nobreak >nul

:: --- Remove old stealth install directory ---
if exist "%INSTALL_DIR%" (
    echo [INFO] Removing old install files...
    takeown /f "%INSTALL_DIR%" /r /d y >nul 2>&1
    icacls "%INSTALL_DIR%" /reset /t /c /q >nul 2>&1
    rmdir /s /q "%INSTALL_DIR%" 2>nul
    if exist "%INSTALL_DIR%" (
        timeout /t 3 /nobreak >nul
        rmdir /s /q "%INSTALL_DIR%" 2>nul
    )
)

:: --- Remove old legacy install directory ---
if exist "%OLD_INSTALL_DIR%" (
    echo [INFO] Removing legacy install directory...
    takeown /f "%OLD_INSTALL_DIR%" /r /d y >nul 2>&1
    icacls "%OLD_INSTALL_DIR%" /reset /t /c /q >nul 2>&1
    rmdir /s /q "%OLD_INSTALL_DIR%" 2>nul
    if exist "%OLD_INSTALL_DIR%" (
        timeout /t 3 /nobreak >nul
        rmdir /s /q "%OLD_INSTALL_DIR%" 2>nul
    )
)

echo [OK] Old installations removed

:: ============================================================================
:: STEP 6: Migrate Data from Old Location (if upgrading)
:: ============================================================================
echo.
echo [INFO] Checking for data migration...

:: If old data exists but new doesn't, migrate it
if exist "%OLD_DATA_DIR%\agent_id" (
    if not exist "%DATA_DIR%\agent_id" (
        echo [INFO] Migrating data from legacy location...
        if not exist "%DATA_DIR%" mkdir "%DATA_DIR%" 2>nul
        
        :: Copy critical identity files
        if exist "%OLD_DATA_DIR%\agent_id" copy /y "%OLD_DATA_DIR%\agent_id" "%DATA_DIR%\agent_id" >nul 2>&1
        if exist "%OLD_DATA_DIR%\local_key" copy /y "%OLD_DATA_DIR%\local_key" "%DATA_DIR%\local_key" >nul 2>&1
        if exist "%OLD_DATA_DIR%\config.json" copy /y "%OLD_DATA_DIR%\config.json" "%DATA_DIR%\config.json" >nul 2>&1
        if exist "%OLD_DATA_DIR%\token.dpapi" copy /y "%OLD_DATA_DIR%\token.dpapi" "%DATA_DIR%\token.dpapi" >nul 2>&1
        if exist "%OLD_DATA_DIR%\token.enc" copy /y "%OLD_DATA_DIR%\token.enc" "%DATA_DIR%\token.enc" >nul 2>&1
        if exist "%OLD_DATA_DIR%\token.salt" copy /y "%OLD_DATA_DIR%\token.salt" "%DATA_DIR%\token.salt" >nul 2>&1
        
        :: Copy buffer data
        if exist "%OLD_DATA_DIR%\buffer" (
            if not exist "%DATA_DIR%\buffer" mkdir "%DATA_DIR%\buffer" 2>nul
            xcopy /s /i /y /q "%OLD_DATA_DIR%\buffer\*" "%DATA_DIR%\buffer\" >nul 2>&1
        )
        
        :: Copy state data
        if exist "%OLD_DATA_DIR%\state" (
            if not exist "%DATA_DIR%\state" mkdir "%DATA_DIR%\state" 2>nul
            xcopy /s /i /y /q "%OLD_DATA_DIR%\state\*" "%DATA_DIR%\state\" >nul 2>&1
        )
        
        echo [OK] Data migrated from legacy location
    )
)

:: ============================================================================
:: STEP 7: Create Directory Structure
:: ============================================================================
echo.
echo [INFO] Creating directories...

:: Cleanup: Remove corrupted data dirs from previous NSSM env var bug
:: (NSSM semicolon bug created dirs like "WinDiagSvc;PYTHONUNBUFFERED=1")
for /d %%D in ("C:\ProgramData\WinDiagSvc;*") do (
    echo [INFO] Removing corrupted directory: %%D
    takeown /f "%%D" /r /d y >nul 2>&1
    icacls "%%D" /reset /t /c /q >nul 2>&1
    rmdir /s /q "%%D" 2>nul
)

mkdir "%INSTALL_DIR%" 2>nul
mkdir "%INSTALL_DIR%\nssm" 2>nul
mkdir "%INSTALL_DIR%\tools" 2>nul
mkdir "%DATA_DIR%" 2>nul
mkdir "%STATE_DIR%" 2>nul
mkdir "%BUFFER_DIR%" 2>nul
mkdir "%LOGS_DIR%" 2>nul

echo [OK] Directories created

:: ============================================================================
:: STEP 8: Copy EXE Files
:: ============================================================================
echo.
echo [INFO] Copying executable files...

copy /y "%CORE_EXE%" "%INSTALL_DIR%\" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy %CORE_EXE%
    pause
    exit /b 1
)

copy /y "%HELPER_EXE%" "%INSTALL_DIR%\" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy %HELPER_EXE%
    pause
    exit /b 1
)

:: Copy NSSM
if exist "nssm\" (
    xcopy /s /i /y /q "nssm\*" "%INSTALL_DIR%\nssm\" >nul
)

:: Copy version marker used for version.json stamping
copy /y "VERSION.txt" "%INSTALL_DIR%\VERSION.txt" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy VERSION.txt
    pause
    exit /b 1
)

:: Copy swapper executable (required for EXE bundle updates)
if not exist "tools\swapper.exe" (
    echo [ERROR] tools\swapper.exe not found in installer package
    pause
    exit /b 1
)
copy /y "tools\swapper.exe" "%INSTALL_DIR%\tools\swapper.exe" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy tools\swapper.exe
    pause
    exit /b 1
)

echo [OK] Files copied

:: Read version from VERSION.txt and write version.json for updater
set "AGENT_VERSION="
for /f "tokens=2 delims=: " %%v in ('findstr /b /c:"Version:" "%INSTALL_DIR%\VERSION.txt"') do set "AGENT_VERSION=%%v"
if "!AGENT_VERSION!"=="" (
    echo [ERROR] Could not parse version from %INSTALL_DIR%\VERSION.txt
    pause
    exit /b 1
)

(
echo {
echo   "version": "!AGENT_VERSION!",
echo   "installed_at": "%DATE% %TIME%",
echo   "install_method": "exe"
echo }
) > "%INSTALL_DIR%\version.json"
echo [OK] version.json created (v!AGENT_VERSION!)

:: ============================================================================
:: STEP 9: Configure Agent Identity (Preserve existing)
:: ============================================================================
echo.
echo [INFO] Configuring agent identity...

:: Check for existing agent_id
if exist "%AGENT_ID_FILE%" (
    set /p AGENT_ID=<"%AGENT_ID_FILE%"
    echo [INFO] Existing agent_id: !AGENT_ID!
) else (
    for /f %%i in ('powershell -Command "[guid]::NewGuid().ToString()"') do set "AGENT_ID=%%i"
    echo !AGENT_ID!>"%AGENT_ID_FILE%"
    echo [INFO] New agent_id: !AGENT_ID!
)

:: ============================================================================
:: BUG FIX: Preserve local_agent_key for re-registration
:: The server checks if local_agent_key matches during re-registration (SEC-023)
:: If we always generate a new key, re-registration will fail with "key mismatch"
:: ============================================================================
set "LOCAL_KEY_FILE=%DATA_DIR%\local_key"
set "LOCAL_KEY="

:: Priority 1: Check for existing key file
if exist "%LOCAL_KEY_FILE%" (
    set /p LOCAL_KEY=<"%LOCAL_KEY_FILE%"
    echo [INFO] Using existing local_key from key file
    goto :key_ready
)

:: Priority 2: Extract from existing config.json
if exist "%CONFIG_FILE%" (
    echo [INFO] Checking existing config.json for local_agent_key...
    for /f "tokens=2 delims=:," %%a in ('findstr /C:"local_agent_key" "%CONFIG_FILE%"') do (
        set "LOCAL_KEY=%%~a"
    )
    :: Clean up the extracted value (remove quotes and spaces)
    set "LOCAL_KEY=!LOCAL_KEY:"=!"
    set "LOCAL_KEY=!LOCAL_KEY: =!"
    if not "!LOCAL_KEY!"=="" (
        echo [INFO] Using existing local_key from config.json
        :: Save to key file for future use
        echo !LOCAL_KEY!>"%LOCAL_KEY_FILE%"
        goto :key_ready
    )
)

:: Priority 3: Generate new key (first-time install only)
echo [INFO] Generating new local_agent_key (first-time install)
for /f %%i in ('powershell -Command "[guid]::NewGuid().ToString()"') do set "LOCAL_KEY=%%i"
echo !LOCAL_KEY!>"%LOCAL_KEY_FILE%"

:key_ready
echo [OK] Identity configured (agent_id and local_key preserved)

:: ============================================================================
:: STEP 10: Create Configuration File (Schema v2)
:: ============================================================================
echo.
echo [INFO] Creating configuration (Schema v2)...

for %%A in ("%COMPUTERNAME%") do set "HOSTNAME=%%~A"

:: Validate registration secret is provided
if "%REGISTRATION_SECRET%"=="" (
    echo.
    echo ========================================================================
    echo   [ERROR] Registration Secret Required
    echo ========================================================================
    echo   The registration secret is REQUIRED for agent installation.
    echo   You must provide the secret from your server administrator.
    echo.
    echo   Without the secret, the agent cannot register with the server.
    echo ========================================================================
    echo.
    set /p "REGISTRATION_SECRET=Enter registration secret (REQUIRED): "
    if "!REGISTRATION_SECRET!"=="" (
        echo [ERROR] Cannot continue without registration secret.
        pause
        exit /b 1
    )
)

(
echo {
echo   "version": 2,
echo   "agent": {
echo     "agent_id": "!AGENT_ID!",
echo     "agent_name": "%HOSTNAME%",
echo     "local_agent_key": "!LOCAL_KEY!"
echo   },
echo   "authentication": {
echo     "api_key": "",
echo     "api_key_stored_securely": false,
echo     "registered": false
echo   },
echo   "server": {
echo     "url": "!SERVER_URL!",
echo     "registration_secret": "!REGISTRATION_SECRET!",
echo     "cert_pinning_fingerprint": "",
echo     "allow_insecure_http": true,
echo     "skip_manifest_verification": false
echo   },
echo   "core": {
echo     "listen_port": 48123,
echo     "aggregation_interval": 60,
echo     "upload_interval": 60,
echo     "heartbeat_interval": 60,
echo     "enable_ingest": true,
echo     "enable_uploader": true,
echo     "enable_aggregator": true
echo   },
echo   "helper": {
echo     "heartbeat_interval": 10,
echo     "domain_interval": 60,
echo     "inventory_interval": 3600,
echo     "features": {
echo       "capture_window_titles": true,
echo       "capture_full_urls": false,
echo       "enable_domains": true,
echo       "enable_inventory": true,
echo       "enable_app_tracking": true,
echo       "enable_idle_tracking": true
echo     }
echo   },
echo   "thresholds": {
echo     "idle_seconds": 120,
echo     "app_specific": {}
echo   },
echo   "retry": {
echo     "max_attempts": 5,
echo     "initial_backoff_seconds": 2,
echo     "max_backoff_seconds": 300
echo   },
echo   "dynamic_reload": {
echo     "enabled": true,
echo     "check_interval": 30
echo   },
echo   "updates": {
echo     "enabled": true,
echo     "check_interval": 1800,
echo     "signing_key": ""
echo   },
echo   "api_token": ""
echo }
) > "%CONFIG_FILE%"

:: Verify config was created and contains registration secret
findstr /C:"registration_secret" "%CONFIG_FILE%" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Config file creation failed - registration_secret missing
    pause
    exit /b 1
)

echo [OK] Configuration created (Schema v2)

:: ============================================================================
:: STEP 11: Set Restrictive Permissions (Enhanced with Deny Delete)
:: ============================================================================
echo.
echo [INFO] Setting file permissions...

:: --- INSTALL DIRECTORY: Locked down ---
:: Reset permissions first
icacls "%INSTALL_DIR%" /reset /t /c /q >nul 2>&1

:: Remove inherited permissions to start clean
icacls "%INSTALL_DIR%" /inheritance:r /c /q >nul 2>&1

:: SYSTEM - Full control (service runs as SYSTEM)
icacls "%INSTALL_DIR%" /grant:r "SYSTEM:(OI)(CI)F" /c /q >nul 2>&1

:: Administrators - Full control (IT admin access)
icacls "%INSTALL_DIR%" /grant:r "Administrators:(OI)(CI)F" /c /q >nul 2>&1

:: Users - Read and Execute only (can run but not modify)
icacls "%INSTALL_DIR%" /grant:r "Users:(OI)(CI)RX" /c /q >nul 2>&1

:: Users - DENY delete (prevents removing EXE files)
icacls "%INSTALL_DIR%" /deny "Users:(OI)(CI)(DE,DC)" /c /q >nul 2>&1

echo [OK] Install directory locked (Users: Read+Execute, Deny Delete)

:: --- DATA DIRECTORY: Service needs write, users limited ---
icacls "%DATA_DIR%" /reset /t /c /q >nul 2>&1

:: Remove inherited permissions
icacls "%DATA_DIR%" /inheritance:r /c /q >nul 2>&1

:: SYSTEM - Full control (service writes logs, state, buffer)
icacls "%DATA_DIR%" /grant:r "SYSTEM:(OI)(CI)F" /c /q >nul 2>&1

:: Administrators - Full control
icacls "%DATA_DIR%" /grant:r "Administrators:(OI)(CI)F" /c /q >nul 2>&1

:: Users - Modify on data dir (Helper runs as user, needs write)
icacls "%DATA_DIR%" /grant:r "Users:(OI)(CI)M" /c /q >nul 2>&1

:: Users - DENY delete on config and identity files specifically
icacls "%DATA_DIR%\config.json" /deny "Users:(DE)" /c /q >nul 2>&1
icacls "%DATA_DIR%\agent_id" /deny "Users:(DE)" /c /q >nul 2>&1
icacls "%DATA_DIR%\local_key" /deny "Users:(DE)" /c /q >nul 2>&1

echo [OK] Data directory permissions set (Users: Modify, critical files protected)

:: ============================================================================
:: STEP 12: Install Core Service (NSSM) with Stealth Name
:: ============================================================================
echo.
echo [INFO] Installing core service...

set "NSSM=%INSTALL_DIR%\nssm\win64\nssm.exe"

if not exist "%NSSM%" (
    echo [ERROR] NSSM not found at: %NSSM%
    pause
    exit /b 1
)

:: Install service with stealth name
"%NSSM%" install %CORE_SVC% "%INSTALL_DIR%\%CORE_EXE%" >nul 2>&1

:: Configure service
"%NSSM%" set %CORE_SVC% AppDirectory "%INSTALL_DIR%" >nul
:: NSSM AppEnvironmentExtra requires multi-string format (NUL-separated)
:: Using PowerShell to set registry value directly for reliable multi-env support
powershell -Command "Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\%CORE_SVC%\Parameters' -Name 'AppEnvironmentExtra' -Value @('SENTINELEDGE_DATA_DIR=%DATA_DIR%','PYTHONUNBUFFERED=1') -Type MultiString" >nul 2>&1
if %errorlevel% neq 0 (
    :: Fallback: set single env var if PowerShell fails
    "%NSSM%" set %CORE_SVC% AppEnvironmentExtra "SENTINELEDGE_DATA_DIR=%DATA_DIR%" >nul
)
"%NSSM%" set %CORE_SVC% Start SERVICE_AUTO_START >nul
"%NSSM%" set %CORE_SVC% AppNoConsole 1 >nul
"%NSSM%" set %CORE_SVC% AppStdout "%LOGS_DIR%\core_stdout.log" >nul
"%NSSM%" set %CORE_SVC% AppStderr "%LOGS_DIR%\core_stderr.log" >nul
"%NSSM%" set %CORE_SVC% AppStdoutCreationDisposition 4 >nul
"%NSSM%" set %CORE_SVC% AppStderrCreationDisposition 4 >nul
"%NSSM%" set %CORE_SVC% AppRotateFiles 1 >nul
"%NSSM%" set %CORE_SVC% AppRotateBytes 10485760 >nul
"%NSSM%" set %CORE_SVC% ObjectName LocalSystem >nul
"%NSSM%" set %CORE_SVC% DisplayName "%CORE_DISPLAY%" >nul
"%NSSM%" set %CORE_SVC% Description "Provides system diagnostic telemetry and health monitoring." >nul

echo [OK] Core service installed as "%CORE_DISPLAY%"

:: ============================================================================
:: STEP 13: Configure SCM Self-Healing (Auto-Restart on Failure)
:: ============================================================================
echo.
echo [INFO] Configuring service recovery...

:: Recovery actions: restart immediately, restart after 5s, restart after 30s
:: Reset failure counter after 24 hours (86400 seconds)
sc failure %CORE_SVC% reset= 86400 actions= restart/0/restart/5000/restart/30000 >nul 2>&1

:: Verify recovery was set
:: Verify recovery was set
sc qfailure %CORE_SVC% | findstr /I "RESTART" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] SCM recovery configured - restart: 0s / 5s / 30s
) else (
    echo [WARN] SCM recovery configuration may have failed
)

:: ============================================================================
:: STEP 14: Create Helper Task (Stealth Name, Interactive User Logon Trigger)
:: ============================================================================
echo.
echo [INFO] Creating helper task for interactive users...

:: Use PowerShell for reliable task creation
set "PS_SCRIPT=%TEMP%\create_helper.ps1"
set "PS_LOG=%TEMP%\create_helper.log"

(
echo # Create Helper task that runs when any interactive user logs in
echo.
echo $helper = "%INSTALL_DIR%\%HELPER_EXE%"
echo $workdir = "%INSTALL_DIR%"
echo.
echo # Action: Run helper EXE directly
echo $action = New-ScheduledTaskAction -Execute $helper -WorkingDirectory $workdir
echo.
echo # Trigger: On any user logon
echo $trigger = New-ScheduledTaskTrigger -AtLogOn
echo.
echo # Principal: Built-in Users group ^(S-1-5-32-545^)
echo # This avoids account name/SID resolution issues on newer Windows builds.
echo $principal = New-ScheduledTaskPrincipal -GroupId "S-1-5-32-545" -RunLevel Limited
echo.
echo # Settings - Hidden makes task invisible in Task Scheduler UI
echo $settings = New-ScheduledTaskSettingsSet `
echo     -AllowStartIfOnBatteries `
echo     -DontStopIfGoingOnBatteries `
echo     -StartWhenAvailable `
echo     -MultipleInstances IgnoreNew `
echo     -ExecutionTimeLimit ^(New-TimeSpan -Days 365^) `
echo     -RestartCount 3 `
echo     -RestartInterval ^(New-TimeSpan -Minutes 5^) `
echo     -Hidden
echo.
echo # Register task with stealth name
echo try {
echo     Unregister-ScheduledTask -TaskName "%HELPER_TASK%" -Confirm:$false -ErrorAction SilentlyContinue
echo     Register-ScheduledTask -TaskName "%HELPER_TASK%" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force -Description "Monitors system health metrics and reports anomalies." ^| Out-Null
echo     Write-Host "[OK] Helper task created for interactive users"
echo } catch {
echo     Write-Host "[ERROR] Task creation failed: $_"
echo     exit 1
echo }
) > "%PS_SCRIPT%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" > "%PS_LOG%" 2>&1
set "PS_RESULT=%errorlevel%"
del "%PS_SCRIPT%" 2>nul

if "%PS_RESULT%" neq "0" (
    echo [WARN] PowerShell method failed, using fallback...
    if exist "%PS_LOG%" (
        echo [INFO] PowerShell task creation error:
        type "%PS_LOG%"
    )

    :: Fallback 1: schtasks default context
    schtasks /create /tn "%HELPER_TASK%" /tr "\"%INSTALL_DIR%\%HELPER_EXE%\"" /sc onlogon /rl limited /f >nul 2>&1
)

:: Fallback 2: explicit INTERACTIVE principal
schtasks /query /tn "%HELPER_TASK%" >nul 2>&1
if %errorlevel% neq 0 (
    schtasks /create /tn "%HELPER_TASK%" /tr "\"%INSTALL_DIR%\%HELPER_EXE%\"" /sc onlogon /ru "INTERACTIVE" /it /rl limited /f >nul 2>&1
)

del "%PS_LOG%" 2>nul

:: Verify task exists
schtasks /query /tn "%HELPER_TASK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Helper task created as "%HELPER_TASK%"
) else (
    echo [WARN] Helper task creation failed - manual setup may be needed
)

:: ============================================================================
:: STEP 15: Start Core Service
:: ============================================================================
echo.
echo [INFO] Starting core service...
timeout /t 2 /nobreak >nul

net start %CORE_SVC% >nul 2>&1
timeout /t 5 /nobreak >nul

sc query %CORE_SVC% | findstr "RUNNING" >nul
if %errorlevel% equ 0 (
    echo [OK] Core service is RUNNING
) else (
    echo [WARN] Service not running - checking logs...
    if exist "%LOGS_DIR%\core_stderr.log" (
        echo.
        echo === Last 10 lines of error log ===
        powershell -Command "Get-Content '%LOGS_DIR%\core_stderr.log' -Tail 10 -ErrorAction SilentlyContinue"
        echo === End of log ===
    )
)

:: ============================================================================
:: STEP 16: Start Helper for Current User
:: ============================================================================
echo.
echo [INFO] Starting helper for current user...
schtasks /run /tn "%HELPER_TASK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Helper started via scheduled task
) else (
    echo [INFO] On some Windows 11 builds, logon-triggered tasks reject on-demand ^(/run^) calls.
    echo [INFO] Trying Start-ScheduledTask fallback...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-ScheduledTask -TaskName '%HELPER_TASK%'" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [OK] Helper started via Start-ScheduledTask
    ) else (
        echo [INFO] Launching helper directly for this session...
        :: Direct launch as current user (non-elevated)
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%INSTALL_DIR%\%HELPER_EXE%' -WorkingDirectory '%INSTALL_DIR%' -WindowStyle Hidden" >nul 2>&1
        timeout /t 3 /nobreak >nul
        tasklist /fi "imagename eq %HELPER_EXE%" 2>nul | findstr /i "%HELPER_EXE%" >nul
        if !errorlevel! equ 0 (
            echo [OK] Helper started via direct launch
        ) else (
            echo [INFO] Helper will start on next user login
        )
    )
)

:: ============================================================================
:: STEP 17: Final Verification
:: ============================================================================
echo.
echo ========================================================================
echo   Installation Summary
echo ========================================================================
echo.
echo   Install Path:    %INSTALL_DIR%
echo   Data Path:       %DATA_DIR%
echo   Agent ID:        !AGENT_ID!
echo   Server:          %SERVER_URL%
echo.
echo ========================================================================
echo   Status
echo ========================================================================

:: Service status - use goto to avoid parentheses issues
sc query %CORE_SVC% | findstr "RUNNING" >nul
if %errorlevel% equ 0 (
    echo   [OK] Core Service:  RUNNING  - %CORE_DISPLAY%
) else (
    echo   [!!] Core Service:  NOT RUNNING
)

:: Task status
schtasks /query /tn "%HELPER_TASK%" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Helper Task:   REGISTERED  - %HELPER_TASK%
) else (
    echo   [!!] Helper Task:   NOT FOUND
)

:: Recovery status
sc qfailure %CORE_SVC% | findstr /I "RESTART" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] SCM Recovery:  ENABLED  - 0s / 5s / 30s
) else (
    echo   [!!] SCM Recovery:  NOT CONFIGURED
)

echo.
echo ========================================================================
echo   Security Features
echo ========================================================================
echo   [OK] Standalone EXE - no Python, no source code
echo   [OK] Stealth service name - %CORE_DISPLAY%
echo   [OK] ACL locked - Users: deny delete
echo   [OK] SCM auto-restart on failure
echo   [OK] SYSTEM-level service - tamper-proof
echo.
echo ========================================================================
echo   Useful Commands - Admin Only
echo ========================================================================
echo.
echo   Check service:  sc query %CORE_SVC%
echo   View recovery:  sc qfailure %CORE_SVC%
echo   View logs:      type "%LOGS_DIR%\core_stderr.log"
echo   Start helper:   schtasks /run /tn "%HELPER_TASK%"
echo.
echo ========================================================================
echo.
pause

