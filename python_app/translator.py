"""Translate localized card/relic names to English for matching.

Loads ``data/game_localization/translation_map.json`` and builds reverse
look-ups from every supported language back to English.

On first access, if the translation map is missing but the game is installed,
it is extracted automatically from the game's PCK file.  If the game is not
found, translation is a no-op — the system falls back to English-only behaviour.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .paths import DATA_DIR

TRANSLATION_MAP_PATH = DATA_DIR / "game_localization" / "translation_map.json"


def _try_auto_extract() -> None:
    """Attempt to extract translations from the game PCK if game is installed."""
    if TRANSLATION_MAP_PATH.exists():
        return
    try:
        from .paths import find_game_dir
        from .pck_extractor import extract_translations
        game_dir = find_game_dir()
        if game_dir is None:
            return
        TRANSLATION_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        result = extract_translations(game_dir)
        with open(TRANSLATION_MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # Non-critical — overlay works without translations


@lru_cache(maxsize=1)
def _load_translation_map() -> dict:
    """Load the full translation map from disk (cached).

    Triggers auto-extraction on first call if the map file is missing.
    """
    _try_auto_extract()
    if not TRANSLATION_MAP_PATH.exists():
        return {}
    with open(TRANSLATION_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _build_reverse_index() -> dict[str, str]:
    """Build a reverse index: lowercased localized name -> English name.

    Covers all languages and both cards and relics.
    """
    tmap = _load_translation_map()
    reverse: dict[str, str] = {}
    for kind in ("cards", "relics"):
        entries = tmap.get(kind, {})
        for _entity_id, langs in entries.items():
            eng_name = langs.get("eng", "")
            if not eng_name:
                continue
            for lang, localized in langs.items():
                if lang == "eng":
                    continue
                key = localized.strip().lower()
                if key and key not in reverse:
                    reverse[key] = eng_name
    return reverse


def _strip_upgrade_suffix(name: str) -> str:
    """Remove trailing '+' or '+N' upgrade markers."""
    return re.sub(r"\+\d*$", "", name).strip()


def to_english(name: str) -> str:
    """Translate a card or relic name to English.

    If the name is already English or no translation is found, returns
    the original name unchanged.
    """
    reverse = _build_reverse_index()
    if not reverse:
        return name

    stripped = _strip_upgrade_suffix(name)
    key = stripped.strip().lower()

    eng = reverse.get(key)
    if eng:
        # Preserve upgrade suffix from the original name
        suffix = name[len(stripped):]
        return eng + suffix

    return name


def to_english_list(names: list[str]) -> list[str]:
    """Translate a list of names to English."""
    reverse = _build_reverse_index()
    if not reverse:
        return names
    return [to_english(n) for n in names]


def is_available() -> bool:
    """Return True if a translation map is loaded and non-empty."""
    return bool(_build_reverse_index())


def invalidate_cache() -> None:
    """Clear cached translation data (e.g. after re-extraction)."""
    _load_translation_map.cache_clear()
    _build_reverse_index.cache_clear()
