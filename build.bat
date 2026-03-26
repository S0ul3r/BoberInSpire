@echo off
setlocal
cd /d "%~dp0"

set "DIST=dist\BoberInSpire"
set "MOD_BUILD=STS2Mods\sts2_example_mod\bin\Release\net9.0"
set "PACK=STS2Mods\sts2_example_mod\pack"

echo [1/6] Building C# mod (Release)...
dotnet build STS2Mods\sts2_example_mod\ExampleMod.csproj -c Release
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo [2/6] Building overlay exe (PyInstaller)...
pyinstaller overlay.spec --noconfirm
if errorlevel 1 (
    echo PyInstaller build failed. Install it: pip install pyinstaller
    exit /b 1
)

echo [3/6] Copying data files into dist...
robocopy data "%DIST%\data" /E /XD "dll dump" "game_localization" __pycache__ /NFL /NDL /NJH /NJS /NC /NS
if errorlevel 8 exit /b 1

echo [4/6] Copying mod files...
mkdir "%DIST%\Mod" 2>nul
copy /Y "%MOD_BUILD%\BoberInSpire.dll" "%DIST%\Mod\"
copy /Y "STS2Mods\sts2_example_mod\BoberInSpire.json" "%DIST%\Mod\"

rem Try to find .pck in game mods folder
for /f "delims=" %%G in ('python -c "from python_app.paths import find_game_dir; g=find_game_dir(); print(g if g else '')" 2^>nul') do set "GAME_DIR=%%G"
if defined GAME_DIR (
    if exist "%GAME_DIR%\mods\BoberInSpire.pck" (
        copy /Y "%GAME_DIR%\mods\BoberInSpire.pck" "%DIST%\Mod\"
    )
)

echo [5/6] Exporting mod .pck (Godot)...
set "GODOT=godot"
if defined GODOT_EXE set "GODOT=%GODOT_EXE%"
if exist "%GODOT%" (
    "%GODOT%" --headless --path "%PACK%" --export-pack "Windows Desktop" "%~dp0%DIST%\Mod\BoberInSpire.pck"
) else (
    if not exist "%DIST%\Mod\BoberInSpire.pck" (
        echo WARNING: BoberInSpire.pck not found. Build the mod once with STS2 closed, or set GODOT_EXE.
    )
)

echo [6/6] Extracting translations (if game found)...
if defined GAME_DIR (
    python scripts\extract_translations.py --game-dir "%GAME_DIR%"
    if exist "data\game_localization\translation_map.json" (
        mkdir "%DIST%\data\game_localization" 2>nul
        copy /Y "data\game_localization\translation_map.json" "%DIST%\data\game_localization\"
    )
) else (
    echo Skipped: game not found. Users can run extract_translations.py later.
)

echo.
echo Build complete: %DIST%
echo   - BoberInSpire.exe (no Python needed!)
echo   - Mod\ (DLL + PCK + JSON)
echo   - data\ (card DB, tier lists, translations)
echo.
echo Next: run "iscc installer.iss" to compile the installer.
endlocal
