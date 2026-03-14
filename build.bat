@echo off
setlocal
cd /d "%~dp0"

set "DIST=dist\BoberInSpire"
set "MOD_BUILD=STS2Mods\sts2_example_mod\bin\Release\net9.0"
set "PACK=STS2Mods\sts2_example_mod\pack"

echo [1/5] Building C# mod (Release)...
dotnet build STS2Mods\sts2_example_mod\ExampleMod.csproj -c Release
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo [2/5] Preparing dist folder...
if not exist "%DIST%\Mod" mkdir "%DIST%\Mod"
if not exist "%DIST%\python_app" mkdir "%DIST%\python_app"
if not exist "%DIST%\data" mkdir "%DIST%\data"

echo [3/5] Copying mod DLL...
copy /Y "%MOD_BUILD%\BoberInSpire.dll" "%DIST%\Mod\"

echo [4/5] Exporting mod .pck (Godot)...
set "GODOT=godot"
if defined GODOT_EXE set "GODOT=%GODOT_EXE%"
if exist "%GODOT%" (
    "%GODOT%" --headless --path "%PACK%" --export-pack "Windows Desktop" "%~dp0%DIST%\Mod\BoberInSpire.pck"
) else (
    echo Godot not found. Copy BoberInSpire.pck manually from game mods folder to %DIST%\Mod\ if needed.
)

echo [5/5] Copying overlay app and data...
xcopy /E /I /Y python_app "%DIST%\python_app\"
xcopy /E /I /Y data "%DIST%\data\"
copy /Y requirements.txt "%DIST%\"

echo.
echo Build complete: %DIST%
echo Next: run "iscc installer.iss" to compile the installer (requires Inno Setup).
endlocal
