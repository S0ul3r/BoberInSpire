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
if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%\Mod"
mkdir "%DIST%\python_app"
mkdir "%DIST%\data"

echo [3/5] Copying mod files (DLL + loader JSON from build output)...
copy /Y "%MOD_BUILD%\BoberInSpire.dll" "%DIST%\Mod\"
copy /Y "STS2Mods\sts2_example_mod\BoberInSpire.json" "%DIST%\Mod\"
rem PostBuild writes DLL, JSON, and PCK directly to the game's mods folder (flat layout — NOT mods\BoberInSpire\)
set "GAME_MODS=%ProgramFiles(x86)%\Steam\steamapps\common\Slay the Spire 2\mods"
if exist "%GAME_MODS%\BoberInSpire.pck" (
    copy /Y "%GAME_MODS%\BoberInSpire.pck" "%DIST%\Mod\"
) else (
    echo WARNING: BoberInSpire.pck not found at "%GAME_MODS%\BoberInSpire.pck"
    echo          Build the mod once with STS2 closed so PostBuild can run Godot, OR set GODOT_EXE and re-run build.bat step 4.
)

echo [4/5] Exporting mod .pck (Godot)...
set "GODOT=godot"
if defined GODOT_EXE set "GODOT=%GODOT_EXE%"
if exist "%GODOT%" (
    "%GODOT%" --headless --path "%PACK%" --export-pack "Windows Desktop" "%~dp0%DIST%\Mod\BoberInSpire.pck"
) else (
    echo Godot not found. Copy BoberInSpire.pck manually from game mods folder to %DIST%\Mod\ if needed.
)

echo [5/5] Copying overlay app and data...
robocopy python_app "%DIST%\python_app" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NC /NS
if errorlevel 8 exit /b 1
robocopy data "%DIST%\data" /E /XD "dll dump" /NFL /NDL /NJH /NJS /NC /NS
if errorlevel 8 exit /b 1
copy /Y requirements.txt "%DIST%\"

echo [6/6] Optional: Tauri overlay shell (Rust + Node required)...
where cargo >nul 2>&1
if errorlevel 1 (
  echo Skipping overlay EXE: cargo not in PATH. Install Rust from https://rustup.rs then re-run build.bat
) else (
  pushd overlay-ui
  call npm install
  if errorlevel 1 (
    echo npm install failed in overlay-ui.
    popd
    exit /b 1
  )
  call npm run tauri build
  popd
  if exist "overlay-ui\src-tauri\target\release\bober-inspire-overlay.exe" (
    copy /Y "overlay-ui\src-tauri\target\release\bober-inspire-overlay.exe" "%DIST%\BoberInSpireOverlay.exe"
    echo Copied BoberInSpireOverlay.exe to dist.
  ) else (
    echo Tauri build did not produce bober-inspire-overlay.exe - check overlay-ui build log above.
  )
)

echo.
echo Build complete: %DIST%
echo Next: run "iscc installer.iss" to compile the installer (requires Inno Setup).
endlocal
