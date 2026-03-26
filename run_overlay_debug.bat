@echo off
cd /d "%~dp0"
set "LOG_DIR=%APPDATA%\SlayTheSpire2"
set "LOG_FILE=%LOG_DIR%\bober_overlay_perf.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo BoberInSpire Overlay DEBUG mode - checking dependencies...
py -3.11 -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Install Python 3.11 and run: py -3.11 -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo [BoberInSpire] Debug run started at %date% %time% > "%LOG_FILE%"
echo [BoberInSpire] Writing overlay perf logs to: %LOG_FILE%
py -3.11 -m python_app.main --debug >> "%LOG_FILE%" 2>&1

echo.
echo Overlay exited. Log file:
echo %LOG_FILE%
pause
