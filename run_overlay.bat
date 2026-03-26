@echo off
cd /d "%~dp0"
if exist "BoberInSpire.exe" (
    start "" "BoberInSpire.exe"
) else (
    echo Running from source...
    py -3 -m python_app.main %*
    if errorlevel 1 (
        echo.
        echo Failed. Make sure Python 3 is installed and in PATH.
        pause
    )
)
