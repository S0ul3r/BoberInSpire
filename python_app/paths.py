"""Centralized path constants and Steam game directory discovery.

All file-system paths used by the overlay and helper scripts are defined
here so that nothing is hardcoded in individual modules.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# ── Project layout ───────────────────────────────────────────────────
# PyInstaller sets sys._MEIPASS; frozen builds keep data/ next to the exe.
import sys as _sys
if getattr(_sys, "frozen", False):
    _BASE_DIR = Path(_sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = _BASE_DIR / "data"

# ── Game state files (written by the C# mod into Godot's user://) ───
_STS2_APPDATA_FOLDER = "SlayTheSpire2"
_COMBAT_STATE_FILE = "bober_combat_state.json"
_REWARD_STATE_FILE = "bober_reward_state.json"

_APPDATA = Path(os.getenv("APPDATA", ""))
GAME_STATE_DIR = _APPDATA / _STS2_APPDATA_FOLDER
DEFAULT_STATE_FILE = GAME_STATE_DIR / _COMBAT_STATE_FILE
DEFAULT_REWARD_FILE = GAME_STATE_DIR / _REWARD_STATE_FILE

# ── Steam / game install ────────────────────────────────────────────
_STEAM_GAME_FOLDER = "Slay the Spire 2"
_GAME_PCK = "SlayTheSpire2.pck"


@lru_cache(maxsize=1)
def steam_library_folders() -> list[Path]:
    """Return all Steam library root paths by parsing ``libraryfolders.vdf``.

    Falls back to the default Steam install location if the VDF is missing.
    """
    steam_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    folders: list[Path] = [steam_root]
    if vdf.exists():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                p = Path(m.group(1))
                if p not in folders:
                    folders.append(p)
        except OSError:
            pass
    return folders


def find_game_dir() -> Path | None:
    """Auto-detect the Slay the Spire 2 install across all Steam libraries."""
    for lib in steam_library_folders():
        candidate = lib / "steamapps" / "common" / _STEAM_GAME_FOLDER
        if (candidate / _GAME_PCK).exists():
            return candidate
    return None
