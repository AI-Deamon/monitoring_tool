@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo    SentinelEdge Server - Easy Deployment
echo ==============================================

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

:: 2. Install Dependencies
echo [SETUP] Installing dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r server_requirements.txt >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

:: 3. Database Setup
echo [DB] Applying database patches and functions...
python apply_sync_functions.py
if %errorlevel% neq 0 (
    echo [ERROR] Database patch failed. Ensure PostgreSQL is running and .env is correct.
    pause
    exit /b 1
)

:: 4. Start Server
echo.
echo ==============================================
echo    Server Starting...
echo ==============================================
echo.

python server_main.py

pause
