@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: SentinelEdge Quick Update Script - Hardened Production Version
:: ============================================================================
:: Stops services → Copies new code → Compiles to .pyc → Starts services
:: PRESERVES: Config, Database, Agent ID, Logs
:: HANDLES: Both hardened (.pyc) and development (.py) installations
:: ============================================================================

cd /d "%~dp0"

echo.
echo ============================================================================
echo SentinelEdge Update - Hardened Production Mode
echo ============================================================================
echo.

:: Check Administrator Privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Administrator privileges required.
    echo Right-click update.bat and select "Run as administrator"
    pause
    exit /b 1
)

:: Define paths
set "INSTALL_DIR=C:\Program Files\SentinelEdge"
set "DATA_DIR=C:\ProgramData\SentinelEdge"
set "LOGS_DIR=%DATA_DIR%\logs"

:: Check if installed
if not exist "%INSTALL_DIR%" (
    echo [ERROR] SentinelEdge is not installed at %INSTALL_DIR%
    echo Please run install.bat first
    pause
    exit /b 1
)

:: ============================================================================
:: STEP 0: Find Python Installation
:: ============================================================================
echo [0/5] Locating Python...

set "PYTHON_EXE="

:: Try common Python locations in priority order
for %%P in (
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Program Files\Python311\python.exe"
    "C:\Program Files\Python310\python.exe"
    "C:\Program Files\Python39\python.exe"
) do (
    if exist %%P (
        set "PYTHON_EXE=%%~P"
        goto :found_python
    )
)

:: Try PATH but exclude WindowsApps stub
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "TEST_PATH=%%i"
    echo !TEST_PATH! | findstr /i /c:"WindowsApps" >nul
    if errorlevel 1 (
        set "PYTHON_EXE=%%i"
        goto :found_python
    )
)

:found_python
if "%PYTHON_EXE%"=="" (
    echo [ERROR] Could not find valid Python installation
    echo Please install Python 3.9+ from python.org
    pause
    exit /b 1
)

echo   [OK] Found Python: %PYTHON_EXE%

:: ============================================================================
:: STEP 0.5: Verify and Fix pywin32 Installation
:: ============================================================================
echo.
echo [0.5/5] Verifying pywin32 installation...

:: Test if pywin32 is working
"%PYTHON_EXE%" -c "import win32api" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] pywin32 is working
    goto :pywin32_done
)

:: Not working - need post-install
echo   [WARN] pywin32 needs post-install configuration...

:: Install/reinstall pywin32 first
echo   - Installing pywin32...
"%PYTHON_EXE%" -m pip install --upgrade pywin32 --quiet --disable-pip-version-check

:: Get Scripts directory using PowerShell (reliable with spaces)
for /f "delims=" %%i in ('powershell -Command "Split-Path -Parent '%PYTHON_EXE%' | Join-Path -ChildPath 'Scripts'"') do (
    set "PYTHON_SCRIPTS=%%i"
)

echo   [DEBUG] Python: "%PYTHON_EXE%"
echo   [DEBUG] Scripts: "%PYTHON_SCRIPTS%"

:: Try post-install
if exist "%PYTHON_SCRIPTS%\pywin32_postinstall.py" (
    echo   - Running pywin32 post-install script...
    echo   [INFO] This registers pywin32 DLLs system-wide
    "%PYTHON_EXE%" "%PYTHON_SCRIPTS%\pywin32_postinstall.py" -install
    if !errorlevel! equ 0 (
        echo   [OK] pywin32 post-install completed
    ) else (
        echo   [WARN] pywin32 post-install failed - may need reboot
    )
) else (
    echo   [WARN] pywin32_postinstall.py not found at "%PYTHON_SCRIPTS%"
    echo   [INFO] Reinstalling pywin32...
    "%PYTHON_EXE%" -m pip uninstall pywin32 -y >nul 2>&1
    "%PYTHON_EXE%" -m pip install pywin32 --disable-pip-version-check
    
    :: Try again after reinstall
    if exist "%PYTHON_SCRIPTS%\pywin32_postinstall.py" (
        echo   - Running pywin32 post-install after reinstall...
        "%PYTHON_EXE%" "%PYTHON_SCRIPTS%\pywin32_postinstall.py" -install
    ) else (
        echo   [FAIL] pywin32_postinstall.py still not found
        echo   [WARN] pywin32 may not work correctly for services
    )
)

:: Final verification
timeout /t 2 /nobreak >nul
"%PYTHON_EXE%" -c "import win32api" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [WARN] pywin32 still not working - reboot may be required
) else (
    echo   [OK] pywin32 is now working
)

:pywin32_done

:: ============================================================================
:: STEP 0.6: Update Dependencies (with verbose output)
:: ============================================================================
echo.
echo [0.6/5] Updating dependencies...

:: Always try to install core dependencies directly (don't rely on requirements.txt path)
echo   - Installing core packages...
"%PYTHON_EXE%" -m pip install --upgrade pip --quiet --disable-pip-version-check 2>nul
"%PYTHON_EXE%" -m pip install pywin32 psutil cryptography requests --upgrade --disable-pip-version-check
if %errorlevel% neq 0 (
    echo   [WARN] Some packages may have failed to install
)

:: Also try requirements.txt if it exists
if exist "requirements.txt" (
    echo   - Installing from requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt --upgrade --disable-pip-version-check
)

:: Verify each critical package
echo.
echo   Verifying installed packages:

"%PYTHON_EXE%" -c "import psutil; print('    [OK] psutil:', psutil.__version__)" 2>nul
if %errorlevel% neq 0 (
    echo     [FAIL] psutil NOT INSTALLED
    echo     [FIX] Run: %PYTHON_EXE% -m pip install psutil
)

"%PYTHON_EXE%" -c "import requests; print('    [OK] requests:', requests.__version__)" 2>nul
if %errorlevel% neq 0 (
    echo     [FAIL] requests NOT INSTALLED
    echo     [FIX] Run: %PYTHON_EXE% -m pip install requests
)

"%PYTHON_EXE%" -c "import cryptography; print('    [OK] cryptography:', cryptography.__version__)" 2>nul
if %errorlevel% neq 0 (
    echo     [FAIL] cryptography NOT INSTALLED
    echo     [FIX] Run: %PYTHON_EXE% -m pip install cryptography
    set "CRYPTO_MISSING=1"
)

"%PYTHON_EXE%" -c "import win32api; print('    [OK] pywin32: installed')" 2>nul
if %errorlevel% neq 0 (
    echo     [FAIL] pywin32 NOT WORKING
    echo     [FIX] Run as Admin - see commands below
    set "PYWIN32_MISSING=1"
)

:: Show summary
if defined CRYPTO_MISSING (
    echo.
    echo   [ERROR] cryptography package is missing!
    echo   The agent will work but secure storage will be disabled.
    echo   To fix, run as Administrator:
    echo     "%PYTHON_EXE%" -m pip install cryptography
    echo.
)

if defined PYWIN32_MISSING (
    echo.
    echo   [ERROR] pywin32 is not working!
    echo   Power management and some features will be disabled.
    echo   To fix, run these commands as Administrator:
    echo.
    echo     cd /d "%PYTHON_EXE:\python.exe=%"
    echo     python.exe Scripts\pywin32_postinstall.py -install
    echo.
)

echo   [DONE] Dependency check complete

:: ============================================================================
:: STEP 1: Stop Services
:: ============================================================================
echo.
echo [1/5] Stopping services...

:: Stop Core service
sc query SentinelEdgeCore | findstr "RUNNING" >nul 2>&1
if %errorlevel% equ 0 (
    echo   - Stopping Core service...
    net stop SentinelEdgeCore >nul 2>&1
    timeout /t 3 /nobreak >nul
    echo   [OK] Core stopped
) else (
    echo   [INFO] Core service not running
)

:: Stop Helper task
schtasks /query /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    echo   - Stopping Helper task...
    schtasks /end /tn "SentinelEdgeUserHelper" >nul 2>&1
    
    :: Kill any orphan pythonw processes running helper
    taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq sentinel_helper*" >nul 2>&1
    
    timeout /t 2 /nobreak >nul
    echo   [OK] Helper stopped
) else (
    echo   [INFO] Helper task not found
)

:: ============================================================================
:: STEP 2: Backup Current Installation
:: ============================================================================
echo.
echo [2/5] Creating backup...

:: Generate timestamp for backup folder
for /f "tokens=2 delims==" %%i in ('wmic os get localdatetime /format:list 2^>nul') do set "dt=%%i"
set "BACKUP_TIMESTAMP=%dt:~0,8%_%dt:~8,6%"
set "BACKUP_DIR=%INSTALL_DIR%_backup_%BACKUP_TIMESTAMP%"

:: Backup core and helper (both .py and .pyc files)
if exist "%INSTALL_DIR%\core" (
    echo   - Backing up to: %BACKUP_DIR%
    xcopy /s /i /y /q "%INSTALL_DIR%\core" "%BACKUP_DIR%\core\" >nul 2>&1
    xcopy /s /i /y /q "%INSTALL_DIR%\helper" "%BACKUP_DIR%\helper\" >nul 2>&1
    
    :: Backup entry points (check for both .py and .pyc)
    if exist "%INSTALL_DIR%\sentinel_core.py" copy /y "%INSTALL_DIR%\sentinel_core.py" "%BACKUP_DIR%\" >nul 2>&1
    if exist "%INSTALL_DIR%\sentinel_core.pyc" copy /y "%INSTALL_DIR%\sentinel_core.pyc" "%BACKUP_DIR%\" >nul 2>&1
    if exist "%INSTALL_DIR%\sentinel_helper.py" copy /y "%INSTALL_DIR%\sentinel_helper.py" "%BACKUP_DIR%\" >nul 2>&1
    if exist "%INSTALL_DIR%\sentinel_helper.pyc" copy /y "%INSTALL_DIR%\sentinel_helper.pyc" "%BACKUP_DIR%\" >nul 2>&1
    
    echo   [OK] Backup created
) else (
    echo   [SKIP] No existing files to backup
)

:: ============================================================================
:: STEP 3: Remove Old Compiled Files and Copy New Source
:: ============================================================================
echo.
echo [3/5] Updating code files...

:: Verify source directories exist
if not exist "core\" (
    echo [ERROR] core\ folder not found in current directory
    echo Please run update.bat from the SentinelEdge distribution folder
    pause
    exit /b 1
)

if not exist "helper\" (
    echo [ERROR] helper\ folder not found
    pause
    exit /b 1
)

:: Clear existing code files (both .py and .pyc) in installation
echo   - Removing old code files...
del /q "%INSTALL_DIR%\core\*.py" >nul 2>&1
del /q "%INSTALL_DIR%\core\*.pyc" >nul 2>&1
del /q "%INSTALL_DIR%\helper\*.py" >nul 2>&1
del /q "%INSTALL_DIR%\helper\*.pyc" >nul 2>&1
del /q "%INSTALL_DIR%\sentinel_core.py" >nul 2>&1
del /q "%INSTALL_DIR%\sentinel_core.pyc" >nul 2>&1
del /q "%INSTALL_DIR%\sentinel_helper.py" >nul 2>&1
del /q "%INSTALL_DIR%\sentinel_helper.pyc" >nul 2>&1

:: Also clean __pycache__ directories
for /d %%d in ("%INSTALL_DIR%\core\__pycache__") do rd /s /q "%%d" 2>nul
for /d %%d in ("%INSTALL_DIR%\helper\__pycache__") do rd /s /q "%%d" 2>nul

:: Copy new source files
echo   - Copying core modules...
xcopy /s /i /y /q "core\*" "%INSTALL_DIR%\core\" >nul
if %errorlevel% neq 0 (
    echo   [ERROR] Failed to copy core files
    pause
    exit /b 1
)

echo   - Copying helper modules...
xcopy /s /i /y /q "helper\*" "%INSTALL_DIR%\helper\" >nul
if %errorlevel% neq 0 (
    echo   [ERROR] Failed to copy helper files
    pause
    exit /b 1
)

:: Copy entry point scripts
echo   - Copying entry points...
copy /y "sentinel_core.py" "%INSTALL_DIR%\" >nul 2>&1
copy /y "sentinel_helper.py" "%INSTALL_DIR%\" >nul 2>&1

:: Copy harden script for compilation
if exist "harden_install.py" copy /y "harden_install.py" "%INSTALL_DIR%\" >nul 2>&1

echo   [OK] Source files copied

:: ============================================================================
:: STEP 4: Security Hardening (Compile to .pyc)
:: ============================================================================
echo.
echo [4/5] Hardening installation (compiling to .pyc)...

:: Check if harden_install.py exists
if exist "%INSTALL_DIR%\harden_install.py" (
    echo   - Compiling Python scripts to bytecode...
    "%PYTHON_EXE%" "%INSTALL_DIR%\harden_install.py" "%INSTALL_DIR%"
    
    :: Remove harden script itself
    del "%INSTALL_DIR%\harden_install.py" >nul 2>&1
    
    echo   [OK] Installation hardened
) else if exist "harden_install.py" (
    echo   - Compiling using local harden script...
    "%PYTHON_EXE%" "harden_install.py" "%INSTALL_DIR%"
    echo   [OK] Installation hardened
) else (
    echo   [WARN] harden_install.py not found - skipping compilation
    echo   [INFO] Installation will use .py source files (less secure)
)

:: Set file permissions (optional, uncomment if needed)
:: echo   - Setting strict file permissions...
:: icacls "%INSTALL_DIR%" /reset /t /c /q >nul
:: icacls "%INSTALL_DIR%" /grant:r "Administrators":(OI)(CI)F /c /q >nul
:: icacls "%INSTALL_DIR%" /grant:r "SYSTEM":(OI)(CI)F /c /q >nul
:: icacls "%INSTALL_DIR%" /grant:r "Users":(OI)(CI)RX /c /q >nul

:: ============================================================================
:: STEP 5: Restart Services
:: ============================================================================
echo.
echo [5/5] Starting services...

:: Start Core service
echo   - Starting Core service...
net start SentinelEdgeCore >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Core started
) else (
    echo   [WARN] Core service failed to start
    echo   Check logs: %LOGS_DIR%\core_stderr.log
    
    :: Show last few lines of error log
    if exist "%LOGS_DIR%\core_stderr.log" (
        echo.
        echo   === Last 10 lines of core_stderr.log ===
        powershell -Command "Get-Content '%LOGS_DIR%\core_stderr.log' -Tail 10" 2>nul
        echo.
    )
)

:: Wait for Core to initialize
timeout /t 5 /nobreak >nul

:: Start Helper task
echo   - Starting Helper task...
schtasks /run /tn "SentinelEdgeUserHelper" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] Helper started
) else (
    echo   [INFO] Helper will start on next login
)

:: ============================================================================
:: Verification
:: ============================================================================
echo.
echo ============================================================================
echo Update Complete!
echo ============================================================================
echo.

:: Check service status
sc query SentinelEdgeCore | findstr "RUNNING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Core Service: RUNNING
) else (
    echo [WARN] Core Service: NOT RUNNING
    echo      Check: %LOGS_DIR%\core_stderr.log
)

:: Check helper
schtasks /query /tn "SentinelEdgeUserHelper" /fo LIST 2>nul | findstr "Status" | findstr "Running" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Helper Task: RUNNING
) else (
    echo [INFO] Helper Task: Will run on login
)

:: Verify files are compiled
if exist "%INSTALL_DIR%\sentinel_core.pyc" (
    echo [OK] Installation: HARDENED (compiled .pyc)
) else if exist "%INSTALL_DIR%\sentinel_core.py" (
    echo [INFO] Installation: Development mode (.py source)
) else (
    echo [WARN] Entry point scripts not found!
)

echo.
echo ============================================================================
echo Quick Commands
echo ============================================================================
echo.
echo View Core logs:
echo   type "%LOGS_DIR%\core.log"
echo.
echo View Helper logs:
echo   type "%%APPDATA%%\SentinelEdge\helper.log"
echo.
echo Check service status:
echo   sc query SentinelEdgeCore
echo.
echo Restart services:
echo   net stop SentinelEdgeCore ^&^& net start SentinelEdgeCore
echo.
echo Rollback to backup:
echo   Copy files from: %BACKUP_DIR%
echo.

:: ============================================================================
:: STEP 6: Configure Browser CDP (Domain Detection)
:: ============================================================================
echo.
echo ============================================================================
echo [6/6] Configuring Browser CDP for Domain Detection...
echo ============================================================================
echo.

:: Create a PowerShell script to modify browser shortcuts
set "CDP_SCRIPT=%TEMP%\configure_cdp.ps1"

(
echo # Configure CDP remote debugging for browser shortcuts
echo $shortcuts = @(
echo     @{Path = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Microsoft Edge.lnk"; Port = 9223},
echo     @{Path = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk"; Port = 9222},
echo     @{Path = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Brave.lnk"; Port = 9224},
echo     @{Path = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Microsoft Edge.lnk"; Port = 9223},
echo     @{Path = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk"; Port = 9222},
echo     @{Path = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Brave.lnk"; Port = 9224},
echo     @{Path = "C:\Users\Public\Desktop\Microsoft Edge.lnk"; Port = 9223},
echo     @{Path = "C:\Users\Public\Desktop\Google Chrome.lnk"; Port = 9222}
echo ^)
echo.
echo $shell = New-Object -ComObject WScript.Shell
echo $configured = 0
echo.
echo foreach ^($item in $shortcuts^) {
echo     if ^(Test-Path $item.Path^) {
echo         try {
echo             $shortcut = $shell.CreateShortcut^($item.Path^)
echo             $cdpFlag = "--remote-debugging-port=$^($item.Port^)"
echo             if ^($shortcut.Arguments -notlike "*remote-debugging-port*"^) {
echo                 if ^($shortcut.Arguments^) {
echo                     $shortcut.Arguments = $shortcut.Arguments + " " + $cdpFlag
echo                 } else {
echo                     $shortcut.Arguments = $cdpFlag
echo                 }
echo                 $shortcut.Save^(^)
echo                 Write-Host "[CDP] Configured: $^($item.Path^)" -ForegroundColor Green
echo                 $configured++
echo             } else {
echo                 Write-Host "[CDP] Already configured: $^($item.Path^)" -ForegroundColor Yellow
echo             }
echo         } catch {
echo             Write-Host "[CDP] Failed to configure: $^($item.Path^) - $_" -ForegroundColor Red
echo         }
echo     }
echo }
echo.
echo if ^($configured -gt 0^) {
echo     Write-Host "[CDP] Configured $configured browser shortcuts" -ForegroundColor Green
echo     Write-Host "[CDP] NOTE: Users must restart their browsers for changes to take effect" -ForegroundColor Cyan
echo } else {
echo     Write-Host "[CDP] No new shortcuts needed configuration" -ForegroundColor Yellow
echo }
) > "%CDP_SCRIPT%"

:: Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%CDP_SCRIPT%" 2>nul
if %errorlevel% equ 0 (
    echo [OK] Browser CDP configuration complete
) else (
    echo [WARN] CDP configuration may have failed - domain detection may use fallback
)

:: Cleanup
del "%CDP_SCRIPT%" 2>nul

echo.
echo ============================================================================
pause
