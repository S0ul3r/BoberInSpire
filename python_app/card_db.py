from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import fuzzy_codex_lookup, normalize_codex_key, strip_bbcode

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
        name_lower = normalize_codex_key(entry["name"])
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
    return fuzzy_codex_lookup(load_card_db(), name)


def enrich_card_description(name: str) -> str:
    info = lookup_card(name)
    if info:
        return info["description"]
    return ""
