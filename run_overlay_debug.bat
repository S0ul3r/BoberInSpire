@echo off
cd /d "%~dp0"
set "LOG_DIR=%APPDATA%\SlayTheSpire2"
set "LOG_FILE=%LOG_DIR%\bober_overlay_perf.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo BoberInSpire Overlay DEBUG mode - checking dependencies...

set "PYRUN="
py -3.11 -c "pass" 2>nul && set "PYRUN=py -3.11"
if not defined PYRUN py -3.13 -c "pass" 2>nul && set "PYRUN=py -3.13"
if not defined PYRUN py -3.12 -c "pass" 2>nul && set "PYRUN=py -3.12"
if not defined PYRUN python -c "pass" 2>nul && set "PYRUN=python"
if not defined PYRUN (
    echo No Python found. Install 3.11+ from https://www.python.org/downloads/ ^(check "Add python.exe to PATH"^).
    pause
    exit /b 1
)

%PYRUN% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo pip install failed. Try: %PYRUN% -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo [BoberInSpire] Debug run started at %date% %time% > "%LOG_FILE%"
echo [BoberInSpire] Writing overlay perf logs to: %LOG_FILE%
%PYRUN% -m python_app.main --debug >> "%LOG_FILE%" 2>&1

echo.
echo Overlay exited. Log file:
echo %LOG_FILE%
pause
