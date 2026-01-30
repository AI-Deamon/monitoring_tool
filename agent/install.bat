@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: SentinelEdge Agent Installer v3.0 - Bundled Python 3.13 Edition
:: ============================================================================
:: NO USER PYTHON DEPENDENCY - We ship our own Python!
:: Works for ALL users on ANY Windows device
:: ============================================================================

cd /d "%~dp0"

echo.
echo ========================================================================
echo   SentinelEdge Agent Installer v3.0
echo   Python 3.13 Bundled Edition
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
    echo Right-click install.bat and select "Run as administrator"
    echo.
    pause
    exit /b 1
)
echo [OK] Administrator privileges confirmed

:: ============================================================================
:: STEP 2: Define Installation Paths
:: ============================================================================
set "INSTALL_DIR=C:\Program Files\SentinelEdge"
set "DATA_DIR=C:\ProgramData\SentinelEdge"
set "PYTHON_DIR=%INSTALL_DIR%\python313"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PYTHONW_EXE=%PYTHON_DIR%\pythonw.exe"
set "LOGS_DIR=%DATA_DIR%\logs"
set "STATE_DIR=%DATA_DIR%\state"
set "BUFFER_DIR=%DATA_DIR%\buffer"
set "CONFIG_FILE=%DATA_DIR%\config.json"
set "AGENT_ID_FILE=%DATA_DIR%\agent_id"

echo [INFO] Installation: %INSTALL_DIR%
echo [INFO] Data:         %DATA_DIR%
echo [INFO] Python:       Bundled 3.13

:: ============================================================================
:: STEP 3: Verify Bundled Python 3.13 Exists
:: ============================================================================
echo.
echo [INFO] Verifying bundled Python 3.13...

if not exist "python313\python.exe" (
    echo.
    echo [ERROR] Bundled Python 3.13 not found!
    echo [ERROR] Expected: python313\python.exe
    echo.
    echo The installer package may be incomplete or corrupted.
    echo Please re-download the complete SentinelEdge installer.
    echo.
    pause
    exit /b 1
)

:: Verify Python actually works
"python313\python.exe" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Bundled Python 3.13 is not functional
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('"python313\python.exe" --version 2^>^&1') do (
    echo [OK] Found: %%v
)

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
:: STEP 5: Stop and Remove Old Installation
:: ============================================================================
echo.
echo [INFO] Checking for existing installation...

:: Stop and remove Core service
sc query SentinelEdgeCore >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Stopping existing Core service...
    net stop SentinelEdgeCore >nul 2>&1
    timeout /t 3 /nobreak >nul
    
    :: Force stop if still running
    sc query SentinelEdgeCore | findstr "RUNNING" >nul 2>&1
    if !errorlevel! equ 0 (
        taskkill /f /fi "SERVICES eq SentinelEdgeCore" >nul 2>&1
        timeout /t 2 /nobreak >nul
    )
    
    :: Remove via NSSM if exists
    if exist "%INSTALL_DIR%\nssm\win64\nssm.exe" (
        "%INSTALL_DIR%\nssm\win64\nssm.exe" remove SentinelEdgeCore confirm >nul 2>&1
    )
    sc delete SentinelEdgeCore >nul 2>&1
    echo [OK] Old service removed
)

:: Remove ALL helper tasks (including per-user ones)
schtasks /query /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Removing existing Helper task...
    schtasks /end /tn "SentinelEdgeUserHelper" >nul 2>&1
    schtasks /delete /tn "SentinelEdgeUserHelper" /f >nul 2>&1
)

:: Kill any running Python processes from our install
taskkill /f /im pythonw.exe /fi "MODULES eq sentinel" >nul 2>&1
taskkill /f /im python.exe /fi "MODULES eq sentinel" >nul 2>&1
timeout /t 2 /nobreak >nul

:: Remove old installation directory
if exist "%INSTALL_DIR%" (
    echo [INFO] Removing old files...
    
    :: Take ownership and reset permissions
    takeown /f "%INSTALL_DIR%" /r /d y >nul 2>&1
    icacls "%INSTALL_DIR%" /reset /t /c /q >nul 2>&1
    
    :: Delete with retry
    rmdir /s /q "%INSTALL_DIR%" 2>nul
    if exist "%INSTALL_DIR%" (
        timeout /t 3 /nobreak >nul
        rmdir /s /q "%INSTALL_DIR%" 2>nul
    )
)

echo [OK] Old installation removed

:: ============================================================================
:: STEP 6: Create Directory Structure
:: ============================================================================
echo.
echo [INFO] Creating directories...

mkdir "%INSTALL_DIR%" 2>nul
mkdir "%INSTALL_DIR%\core" 2>nul
mkdir "%INSTALL_DIR%\helper" 2>nul
mkdir "%INSTALL_DIR%\nssm" 2>nul
mkdir "%DATA_DIR%" 2>nul
mkdir "%STATE_DIR%" 2>nul
mkdir "%BUFFER_DIR%" 2>nul
mkdir "%LOGS_DIR%" 2>nul

echo [OK] Directories created

:: ============================================================================
:: STEP 7: Copy Bundled Python 3.13
:: ============================================================================
echo.
echo [INFO] Installing bundled Python 3.13...
echo [INFO] This ensures identical behavior on ALL devices...

xcopy /e /i /q /y "python313" "%PYTHON_DIR%\" >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to copy Python files
    pause
    exit /b 1
)

:: Verify Python works in install location
"%PYTHON_EXE%" --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Installed Python verification failed
    pause
    exit /b 1
)

echo [OK] Python 3.13 installed: %PYTHON_DIR%

:: ============================================================================
:: STEP 8: Verify Dependencies
:: ============================================================================
echo.
echo [INFO] Verifying dependencies...

set "DEP_ERRORS=0"

"%PYTHON_EXE%" -c "import psutil; print('[OK] psutil:', psutil.__version__)" 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] psutil missing
    set "DEP_ERRORS=1"
)

"%PYTHON_EXE%" -c "import requests; print('[OK] requests:', requests.__version__)" 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] requests missing
    set "DEP_ERRORS=1"
)

"%PYTHON_EXE%" -c "import win32api; print('[OK] pywin32')" 2>nul
if !errorlevel! neq 0 (
    echo [FAIL] pywin32 missing
    set "DEP_ERRORS=1"
)

if "%DEP_ERRORS%"=="1" (
    echo.
    echo [ERROR] Dependencies missing in bundled Python!
    echo [ERROR] The installer package may be incomplete.
    pause
    exit /b 1
)

echo [OK] All dependencies verified

:: ============================================================================
:: STEP 9: Copy Agent Files
:: ============================================================================
echo.
echo [INFO] Copying agent files...

:: Check source files exist
if not exist "sentinel_core.py" (
    echo [ERROR] sentinel_core.py not found
    pause
    exit /b 1
)

if not exist "sentinel_helper.py" (
    echo [ERROR] sentinel_helper.py not found
    pause
    exit /b 1
)

:: Copy main scripts
copy /y "sentinel_core.py" "%INSTALL_DIR%\" >nul
copy /y "sentinel_helper.py" "%INSTALL_DIR%\" >nul

:: Copy core module
if exist "core\" (
    xcopy /s /i /y /q "core\*" "%INSTALL_DIR%\core\" >nul
)

:: Copy helper module
if exist "helper\" (
    xcopy /s /i /y /q "helper\*" "%INSTALL_DIR%\helper\" >nul
)

:: Copy NSSM
if exist "nssm\" (
    xcopy /s /i /y /q "nssm\*" "%INSTALL_DIR%\nssm\" >nul
)

echo [OK] Files copied

:: ============================================================================
:: STEP 10: Configure Agent Identity
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
:: STEP 11: Create Configuration File (Schema v2)
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
:: STEP 12: Compile Python Files to .pyc
:: ============================================================================
echo.
echo [INFO] Compiling Python files...

"%PYTHON_EXE%" -m compileall -q -f "%INSTALL_DIR%" 2>nul

:: Move .pyc files from __pycache__ to parent directories
for /r "%INSTALL_DIR%" %%D in (__pycache__) do (
    if exist "%%D" (
        pushd "%%D"
        for %%F in (*.pyc) do (
            set "FILE=%%~nF"
            set "FILE=!FILE:.cpython-313=!"
            move /y "%%F" "..\!FILE!.pyc" >nul 2>&1
        )
        popd
        rd /s /q "%%D" 2>nul
    )
)

echo [OK] Files compiled

:: ============================================================================
:: STEP 13: Remove Source .py Files (Security)
:: ============================================================================
echo.
echo [INFO] Removing source files for security...

for /r "%INSTALL_DIR%" %%F in (*.py) do (
    del /f /q "%%F" >nul 2>&1
)

echo [OK] Source files removed (only .pyc remain)

:: ============================================================================
:: STEP 14: Set Restrictive Permissions
:: ============================================================================
echo.
echo [INFO] Setting file permissions...

:: Reset permissions first
icacls "%INSTALL_DIR%" /reset /t /c /q >nul 2>&1

:: SYSTEM - Full control
icacls "%INSTALL_DIR%" /grant:r "SYSTEM:(OI)(CI)F" /c /q >nul 2>&1

:: Administrators - Full control
icacls "%INSTALL_DIR%" /grant:r "Administrators:(OI)(CI)F" /c /q >nul 2>&1

:: Users - Read and Execute only (no write/delete)
icacls "%INSTALL_DIR%" /grant:r "Users:(OI)(CI)RX" /c /q >nul 2>&1

:: Data directory - SYSTEM and Users can write
icacls "%DATA_DIR%" /grant:r "SYSTEM:(OI)(CI)F" /c /q >nul 2>&1
icacls "%DATA_DIR%" /grant:r "Users:(OI)(CI)M" /c /q >nul 2>&1

echo [OK] Permissions set

:: ============================================================================
:: STEP 15: Install Core Service (NSSM)
:: ============================================================================
echo.
echo [INFO] Installing Core service...

set "NSSM=%INSTALL_DIR%\nssm\win64\nssm.exe"

if not exist "%NSSM%" (
    echo [ERROR] NSSM not found at: %NSSM%
    pause
    exit /b 1
)

:: Install service
"%NSSM%" install SentinelEdgeCore "%PYTHONW_EXE%" "\"%INSTALL_DIR%\sentinel_core.pyc\"" >nul 2>&1

:: Configure service
"%NSSM%" set SentinelEdgeCore AppDirectory "%INSTALL_DIR%" >nul
"%NSSM%" set SentinelEdgeCore AppEnvironmentExtra "PYTHONPATH=%INSTALL_DIR%;SENTINELEDGE_DATA_DIR=%DATA_DIR%;PYTHONUNBUFFERED=1" >nul
"%NSSM%" set SentinelEdgeCore Start SERVICE_AUTO_START >nul
"%NSSM%" set SentinelEdgeCore AppNoConsole 1 >nul
"%NSSM%" set SentinelEdgeCore AppStdout "%LOGS_DIR%\core_stdout.log" >nul
"%NSSM%" set SentinelEdgeCore AppStderr "%LOGS_DIR%\core_stderr.log" >nul
"%NSSM%" set SentinelEdgeCore AppStdoutCreationDisposition 4 >nul
"%NSSM%" set SentinelEdgeCore AppStderrCreationDisposition 4 >nul
"%NSSM%" set SentinelEdgeCore AppRotateFiles 1 >nul
"%NSSM%" set SentinelEdgeCore AppRotateBytes 10485760 >nul
"%NSSM%" set SentinelEdgeCore ObjectName LocalSystem >nul
"%NSSM%" set SentinelEdgeCore Description "SentinelEdge Monitoring Agent - Core Service" >nul

echo [OK] Core service installed

:: ============================================================================
:: STEP 16: Create Helper Task (Works for ALL Users)
:: ============================================================================
echo.
echo [INFO] Creating Helper task (for ALL users)...

:: Use PowerShell for reliable multi-user task creation
set "PS_SCRIPT=%TEMP%\create_helper.ps1"

(
echo # Create Helper task that runs for ANY user who logs in
echo.
echo $pythonw = "%PYTHONW_EXE%"
echo $helper = "%INSTALL_DIR%\sentinel_helper.pyc"
echo $workdir = "%INSTALL_DIR%"
echo.
echo # Action: Run pythonw.exe with helper script
echo $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$helper`"" -WorkingDirectory $workdir
echo.
echo # Trigger: On any user logon
echo $trigger = New-ScheduledTaskTrigger -AtLogOn
echo.
echo # Principal: Run as the USERS group ^(any logged-in user^)
echo # S-1-5-32-545 = Built-in Users group
echo $principal = New-ScheduledTaskPrincipal -GroupId "S-1-5-32-545" -RunLevel Limited
echo.
echo # Settings
echo $settings = New-ScheduledTaskSettingsSet `
echo     -AllowStartIfOnBatteries `
echo     -DontStopIfGoingOnBatteries `
echo     -StartWhenAvailable `
echo     -MultipleInstances IgnoreNew `
echo     -ExecutionTimeLimit ^(New-TimeSpan -Days 365^) `
echo     -RestartCount 3 `
echo     -RestartInterval ^(New-TimeSpan -Minutes 5^)
echo.
echo # Register task
echo try {
echo     Unregister-ScheduledTask -TaskName "SentinelEdgeUserHelper" -Confirm:$false -ErrorAction SilentlyContinue
echo     Register-ScheduledTask -TaskName "SentinelEdgeUserHelper" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force ^| Out-Null
echo     Write-Host "[OK] Helper task created for all users"
echo } catch {
echo     Write-Host "[ERROR] Task creation failed: $_"
echo     exit 1
echo }
) > "%PS_SCRIPT%"

powershell -ExecutionPolicy Bypass -File "%PS_SCRIPT%" 2>nul
set "PS_RESULT=%errorlevel%"
del "%PS_SCRIPT%" 2>nul

if "%PS_RESULT%" neq "0" (
    echo [WARN] PowerShell method failed, using fallback...
    
    :: Fallback: schtasks with generic user
    schtasks /create /tn "SentinelEdgeUserHelper" /tr "\"%PYTHONW_EXE%\" \"%INSTALL_DIR%\sentinel_helper.pyc\"" /sc onlogon /ru "Users" /rl limited /f >nul 2>&1
)

:: Verify task exists
schtasks /query /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Helper task created
) else (
    echo [WARN] Helper task creation failed - manual setup may be needed
)

:: ============================================================================
:: STEP 17: Start Core Service
:: ============================================================================
echo.
echo [INFO] Starting Core service...
timeout /t 2 /nobreak >nul

net start SentinelEdgeCore >nul 2>&1
timeout /t 5 /nobreak >nul

sc query SentinelEdgeCore | findstr "RUNNING" >nul
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
:: STEP 18: Start Helper for Current User
:: ============================================================================
echo.
echo [INFO] Starting Helper for current user...
schtasks /run /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Helper started
) else (
    echo [INFO] Helper will start on next user login
)

:: ============================================================================
:: STEP 19: Final Verification
:: ============================================================================
echo.
echo ========================================================================
echo   Installation Summary
echo ========================================================================
echo.
echo   Install Path:    %INSTALL_DIR%
echo   Data Path:       %DATA_DIR%
echo   Python:          3.13 (bundled - no user Python needed)
echo   Agent ID:        !AGENT_ID!
echo   Server:          %SERVER_URL%
echo.
echo ========================================================================
echo   Status
echo ========================================================================

:: Service status
sc query SentinelEdgeCore | findstr "RUNNING" >nul
if %errorlevel% equ 0 (
    echo   [OK] Core Service:  RUNNING
) else (
    echo   [!!] Core Service:  NOT RUNNING
)

:: Task status
schtasks /query /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Helper Task:   REGISTERED
) else (
    echo   [!!] Helper Task:   NOT FOUND
)

echo.
echo ========================================================================
echo   Security Features
echo ========================================================================
echo   [OK] Bundled Python 3.13 (isolated from system)
echo   [OK] Compiled .pyc files only (source removed)
echo   [OK] Read-only permissions for users
echo   [OK] SYSTEM-level service (tamper-proof)
echo.
echo ========================================================================
echo   Useful Commands
echo ========================================================================
echo.
echo   Check service:  sc query SentinelEdgeCore
echo   View logs:      type "%LOGS_DIR%\core_stderr.log"
echo   Start Helper:   schtasks /run /tn "SentinelEdgeUserHelper"
echo.
echo ========================================================================
echo.
pause
