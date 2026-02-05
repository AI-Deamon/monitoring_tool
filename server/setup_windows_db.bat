@echo off
REM ============================================================================
REM SentinelEdge Server - Windows Database Setup Script
REM ============================================================================
TITLE SentinelEdge Database Setup
COLOR 0A

echo.
echo ============================================================================
echo  SentinelEdge Server - Database Setup for Windows
echo ============================================================================
echo.

REM Check if PostgreSQL is installed
where psql >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PostgreSQL is not installed or not in PATH
    echo Please install PostgreSQL 16 and add it to your PATH
    echo Download from: https://www.postgresql.org/download/windows/
    pause
    exit /b 1
)

echo [1/5] PostgreSQL found!
echo.

REM Get PostgreSQL bin path
for /f "delims=" %%i in ('where psql') do set PSQL_PATH=%%i
for %%i in ("%PSQL_PATH%") do set PG_BIN_DIR=%%~dpi

echo PostgreSQL bin directory: %PG_BIN_DIR%
echo.

REM Prompt for backup file location
set /p BACKUP_FILE="Enter full path to backup file (e.g., C:\backup\sentineledge_backup.dump): "

IF NOT EXIST "%BACKUP_FILE%" (
    echo [ERROR] Backup file not found: %BACKUP_FILE%
    pause
    exit /b 1
)

echo [2/5] Backup file found: %BACKUP_FILE%
echo.

REM Prompt for PostgreSQL password
echo [3/5] Enter PostgreSQL 'postgres' user password:
set /p PGPASSWORD="Password: "

echo.
echo [4/5] Creating database and user...
echo.

REM Create database and user using psql
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "DROP DATABASE IF EXISTS sentinel_edge_v1;" 2>nul
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "DROP USER IF EXISTS sentinelserver;" 2>nul
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "CREATE USER sentinelserver WITH PASSWORD 'sentinel_edge_secure';"
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "CREATE DATABASE sentinel_edge_v1 OWNER sentinelserver;"
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sentinel_edge_v1 TO sentinelserver;"

IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to create database or user
    pause
    exit /b 1
)

echo [OK] Database and user created successfully!
echo.

echo [5/5] Restoring backup...
echo This may take a few minutes depending on the backup size...
echo.

REM Restore the backup
"%PG_BIN_DIR%pg_restore.exe" -h localhost -U postgres -d sentinel_edge_v1 -v "%BACKUP_FILE%"

IF %ERRORLEVEL% NEQ 0 (
    echo [WARN] Restore completed with warnings (this is normal for some constraints)
) ELSE (
    echo [OK] Backup restored successfully!
)

echo.
echo ============================================================================
echo  Database Setup Complete!
echo ============================================================================
echo.
echo Next steps:
echo 1. Update .env file with: DATABASE_URL=postgresql://sentinelserver:sentinel_edge_secure@localhost:5432/sentinel_edge_v1
echo 2. Run: start_server.bat
echo.
pause
