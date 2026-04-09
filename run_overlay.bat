@echo off
cd /d "%~dp0"
echo BoberInSpire Overlay - checking dependencies...

set "PYRUN="
py -3.11 -c "pass" 2>nul && set "PYRUN=py -3.11"
if not defined PYRUN py -3.13 -c "pass" 2>nul && set "PYRUN=py -3.13"
if not defined PYRUN py -3.12 -c "pass" 2>nul && set "PYRUN=py -3.12"
if not defined PYRUN python -c "pass" 2>nul && set "PYRUN=python"
if not defined PYRUN (
    echo No Python found. Install 3.11+ from https://www.python.org/downloads/ ^(check "Add python.exe to PATH"^).
    echo Then verify: py --list   or   python --version
    pause
    exit /b 1
)

%PYRUN% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo pip install failed. Try: %PYRUN% -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" %PYRUN% -m python_app.main
exit /b 0
