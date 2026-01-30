@echo off
:: Quick restart without file copy - useful for config changes

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Run as Administrator!
    pause
    exit /b 1
)

echo Restarting SentinelEdge services...
echo.

echo Stopping Core...
net stop SentinelEdgeCore >nul 2>&1
timeout /t 2 /nobreak >nul

echo Stopping Helper...
schtasks /end /tn "SentinelEdgeUserHelper" >nul 2>&1
timeout /t 1 /nobreak >nul

echo.
echo Starting Core...
net start SentinelEdgeCore >nul 2>&1

timeout /t 3 /nobreak >nul

echo Starting Helper...
schtasks /run /tn "SentinelEdgeUserHelper" >nul 2>&1

echo.
echo Done!
timeout /t 2
