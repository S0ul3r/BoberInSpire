@echo off
cd /d "%~dp0"
echo BoberInSpire Overlay - checking dependencies...
py -3.11 -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Install Python 3.11 and run: py -3.11 -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" py -3.11 -m python_app.main
exit /b 0
