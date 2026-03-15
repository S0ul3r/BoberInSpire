from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import strip_bbcode

_DB: dict[str, dict[str, Any]] = {}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RELIC_FILE = DATA_DIR / "spire_codex_relics.json"

RARITY_ORDER = {
    "ancient": 0,
    "rare": 1,
    "shop": 2,
    "uncommon": 3,
    "event": 4,
    "common": 5,
    "starter": 6,
}

RARITY_COLORS = {
    "ancient": "#ff44ff",
    "rare": "#ffd700",
    "shop": "#00ccff",
    "uncommon": "#44ff44",
    "event": "#ff8844",
    "common": "#cccccc",
    "starter": "#888888",
}


def load_relic_db(path: Path | None = None) -> dict[str, dict[str, Any]]:
    global _DB
    if _DB:
        return _DB

    path = path or RELIC_FILE
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
            "short_description": entry.get("short_description", ""),
            "rarity": entry.get("rarity", "").lower(),
            "pool": entry.get("pool", ""),
        }

    return _DB


def lookup_relic(name: str) -> dict[str, Any] | None:
    db = load_relic_db()
    result = db.get(name.lower().strip())
    if result:
        return result

    for key, val in db.items():
        if name.lower().strip() in key or key in name.lower().strip():
            return val
    return None


def enrich_relic_description(name: str) -> str:
    info = lookup_relic(name)
    if info:
        return info["description"]
    return ""


def get_short_description(name: str) -> str:
    info = lookup_relic(name)
    if info:
        return info.get("short_description", "") or info["description"][:50]
    return ""


def get_short_description_only(name: str) -> str:
    """Return only the short_description field; no fallback to full description.
    Use for RELIC BONUSES so relics with empty short_description are excluded."""
    info = lookup_relic(name)
    if info:
        return (info.get("short_description") or "").strip()
    return ""


def rarity_sort_key(rarity: str) -> int:
    return RARITY_ORDER.get(rarity.lower(), 99)


def rarity_color(rarity: str) -> str:
    return RARITY_COLORS.get(rarity.lower(), "#cccccc")


def summarize_relic_bonuses(relics: list[dict[str, str]]) -> list[str]:
    """Analyze relic descriptions and return a list of bonus summary lines."""
    bonuses: list[str] = []

    damage_bonuses: list[str] = []
    block_bonuses: list[str] = []
    heal_bonuses: list[str] = []
    energy_bonuses: list[str] = []
    other_bonuses: list[str] = []

    damage_keywords = [
        "damage", "strength", "vigor", "vulnerable", "attack",
        "deal", "extra damage", "thorns",
    ]
    block_keywords = [
        "block", "dexterity", "plated armor", "metallicize",
        "shield", "armor",
    ]
    heal_keywords = [
        "heal", "hp", "max hp", "regenerat", "restore",
        "life", "rest site",
    ]
    energy_keywords = [
        "energy", "additional energy", "gain.*energy",
    ]

    for relic in relics:
        name = relic.get("name", "")
        desc = relic.get("description", "")
        if not desc:
            desc = enrich_relic_description(name)
        if not desc:
            continue

        desc_lower = desc.lower()

        if any(kw in desc_lower for kw in damage_keywords):
            damage_bonuses.append(f"{name}: {desc}")

        if any(kw in desc_lower for kw in block_keywords):
            block_bonuses.append(f"{name}: {desc}")

        if any(kw in desc_lower for kw in heal_keywords):
            heal_bonuses.append(f"{name}: {desc}")

        if any(kw in desc_lower for kw in energy_keywords):
            energy_bonuses.append(f"{name}: {desc}")

        already_categorized = any(
            any(kw in desc_lower for kw in kws)
            for kws in [damage_keywords, block_keywords, heal_keywords, energy_keywords]
        )
        if not already_categorized:
            other_bonuses.append(f"{name}: {desc}")

    if damage_bonuses:
        bonuses.append("DMG: " + " | ".join(damage_bonuses))
    if block_bonuses:
        bonuses.append("BLK: " + " | ".join(block_bonuses))
    if heal_bonuses:
        bonuses.append("HEAL: " + " | ".join(heal_bonuses))
    if energy_bonuses:
        bonuses.append("NRG: " + " | ".join(energy_bonuses))
    if other_bonuses:
        bonuses.append("OTHER: " + " | ".join(other_bonuses))

    return bonuses
