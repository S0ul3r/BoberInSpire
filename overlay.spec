# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BoberInSpire overlay.

Build:  pyinstaller overlay.spec
Output: dist/BoberInSpire/BoberInSpire.exe  (one-dir mode for fast startup)
"""

a = Analysis(
    ["overlay_entry.py"],
    pathex=[],
    binaries=[],
    datas=[],           # data/ is copied separately by build.bat
    hiddenimports=[
        "watchdog",
        "watchdog.observers",
        "watchdog.observers.polling",
        "watchdog.observers.read_directory_changes",
        "watchdog.events",
        "keyboard",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["unittest", "test", "tests", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BoberInSpire",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window — Tkinter overlay only
    icon="python_app/icon.ico" if __import__("os").path.exists("python_app/icon.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BoberInSpire",
)
