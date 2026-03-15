from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import strip_bbcode

_DB: dict[str, dict[str, Any]] = {}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CARD_FILE = DATA_DIR / "spire_codex_cards.json"


def load_card_db(path: Path | None = None) -> dict[str, dict[str, Any]]:
    global _DB
    if _DB:
        return _DB

    path = path or CARD_FILE
    if not path.exists():
        return _DB

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    for entry in raw:
        name_lower = entry["name"].lower().strip()
        _DB[name_lower] = {
            "id": entry.get("id", ""),
            "name": entry["name"],
            "description": strip_bbcode(entry.get("description", "")),
            "type": entry.get("type", ""),
            "cost": entry.get("cost", ""),
            "rarity": entry.get("rarity", ""),
            "color": entry.get("color", ""),
        }

    return _DB


def lookup_card(name: str) -> dict[str, Any] | None:
    db = load_card_db()
    result = db.get(name.lower().strip())
    if result:
        return result

    for key, val in db.items():
        if name.lower().strip() in key or key in name.lower().strip():
            return val
    return None


def enrich_card_description(name: str) -> str:
    info = lookup_card(name)
    if info:
        return info["description"]
    return ""
