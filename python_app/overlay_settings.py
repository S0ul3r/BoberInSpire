"""Persistent overlay UI toggles + transparency (JSON in %APPDATA%\\SlayTheSpire2)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class OverlaySettings:
    """Which panels to render and window alpha. Disabled panels skip heavy work (strategy, recommend, etc.)."""

    show_combat_summary: bool = True  # HP/energy row + net damage / block banner
    show_enemies: bool = False
    show_strategy: bool = False
    show_relics: bool = True
    show_merchant_relics: bool = True
    show_card_reward: bool = True
    alpha: float = 0.9  # 0.35 .. 1.0
    click_through: bool = False  # mouse passes to desktop / game (Tauri overlay)


def default_settings_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "SlayTheSpire2" / "bober_overlay_settings.json"


def load_settings(path: Path | None = None) -> OverlaySettings:
    p = path or default_settings_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return OverlaySettings()
    try:
        return OverlaySettings(
            show_combat_summary=bool(raw.get("show_combat_summary", True)),
            show_enemies=bool(raw.get("show_enemies", False)),
            show_strategy=bool(raw.get("show_strategy", False)),
            show_relics=bool(raw.get("show_relics", True)),
            show_merchant_relics=bool(raw.get("show_merchant_relics", True)),
            show_card_reward=bool(raw.get("show_card_reward", True)),
            alpha=float(raw.get("alpha", 0.9)),
            click_through=bool(raw.get("click_through", False)),
        )
    except (TypeError, ValueError):
        return OverlaySettings()


def save_settings(settings: OverlaySettings, path: Path | None = None) -> None:
    p = path or default_settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    a = max(0.35, min(1.0, settings.alpha))
    data = asdict(settings)
    data["alpha"] = a
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
