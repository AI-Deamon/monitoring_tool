@echo off
REM ============================================================================
REM SentinelEdge Server - Fresh Database Setup (No venv required)
REM ============================================================================
TITLE SentinelEdge - Fresh Database Setup
COLOR 0E
CD /D "%~dp0"

echo.
echo ============================================================================
echo  SentinelEdge Server - Fresh Database Setup
echo ============================================================================
echo.
echo This will:
echo  1. Drop existing database (if any)
echo  2. Create fresh database and user
echo  3. Run all Alembic migrations
echo.
echo WARNING: This will DELETE all existing data!
echo.
set /p CONFIRM="Type 'YES' to continue: "

IF NOT "%CONFIRM%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo [1/5] Checking PostgreSQL...
where psql >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PostgreSQL not found in PATH
    echo Please install PostgreSQL 16 and add to PATH
    pause
    exit /b 1
)

for /f "delims=" %%i in ('where psql') do set PSQL_PATH=%%i
for %%i in ("%PSQL_PATH%") do set PG_BIN_DIR=%%~dpi
echo [OK] PostgreSQL found: %PG_BIN_DIR%

echo.
echo [2/5] Enter PostgreSQL 'postgres' user password:
set /p PGPASSWORD="Password: "

echo.
echo [3/5] Creating fresh database...

REM Drop existing database and user
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "DROP DATABASE IF EXISTS sentinel_edge_v1;" 2>nul
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "DROP USER IF EXISTS sentinelserver;" 2>nul

REM Create new user and database
"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "CREATE USER sentinelserver WITH PASSWORD 'sentinel_edge_secure';"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to create user
    pause
    exit /b 1
)

"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "CREATE DATABASE sentinel_edge_v1 OWNER sentinelserver;"
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to create database
    pause
    exit /b 1
)

"%PG_BIN_DIR%psql.exe" -h localhost -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sentinel_edge_v1 TO sentinelserver;"

echo [OK] Database created: sentinel_edge_v1

echo.
echo [4/5] Checking Python dependencies...
python -c "import flask, sqlalchemy, alembic" 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [WARN] Some dependencies missing. Installing...
    pip install -r server_requirements.txt
    IF %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install dependencies
        echo Please run: pip install -r server_requirements.txt
        pause
        exit /b 1
    )
)
echo [OK] Python dependencies ready

echo.
echo [5/5] Running database migrations...
echo This will create all tables, indexes, and stored procedures...
echo.

python -m alembic upgrade head

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Migration failed!
    echo.
    echo Troubleshooting:
    echo  1. Check if alembic is installed: pip install alembic
    echo  2. Check DATABASE_URL in .env file
    echo  3. Check PostgreSQL is running
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] All migrations applied successfully!

echo.
echo ============================================================================
echo  Fresh Database Setup Complete!
echo ============================================================================
echo.
echo Database Details:
echo   Host:     localhost
echo   Port:     5432
echo   Database: sentinel_edge_v1
echo   User:     sentinelserver
echo   Password: sentinel_edge_secure
echo.
echo Next Steps:
echo   1. Run: python server_main.py
echo   2. Open: http://localhost:5050/dashboard/
echo   3. Login: admin / changeme123
echo.
echo The database is ready to receive agent data!
echo ============================================================================
echo.
pause
