"""Extract localization data from the Slay the Spire 2 Godot PCK file.

The PCK stores ``localization/{lang}/cards.json`` and ``relics.json`` with
card/relic names in every supported language.  This module reads the PCK
file index (stored near the end of the file), extracts the JSON blobs, and
returns a unified mapping keyed by entity ID.

Output structure::

    {
      "cards":  {"ABRASIVE": {"eng": "Abrasive", "rus": "Дикобраз", ...}, ...},
      "relics": {"AKABEKO":  {"eng": "Akabeko",  "rus": "Акабеко",  ...}, ...},
    }
"""
from __future__ import annotations

import json
import mmap
import re
import struct
from pathlib import Path

_GAME_PCK = "SlayTheSpire2.pck"
# The Godot PCK file index lives near the end; search this many bytes back.
_PCK_INDEX_SEARCH_WINDOW = 10_000_000
# Extra bytes to read past the recorded file size to handle alignment padding.
_PCK_BOUNDARY_BUFFER = 4096


def _find_pck_entry(mm: mmap.mmap, path_str: str, search_start: int) -> tuple[int, int, int] | None:
    """Find a file entry in the PCK index by its path string.

    Returns (offset, size, flags) or None.
    """
    target = path_str.encode("utf-8")
    pos = mm.find(target, search_start)
    if pos == -1:
        return None
    mm.seek(pos - 4)
    pl = struct.unpack("<I", mm.read(4))[0]
    mm.read(pl)  # skip path bytes
    offset = struct.unpack("<Q", mm.read(8))[0]
    size = struct.unpack("<Q", mm.read(8))[0]
    mm.read(16)  # md5
    flags = struct.unpack("<I", mm.read(4))[0]
    return offset, size, flags


def _extract_json_objects(data: bytes) -> dict[str, str]:
    """Parse all top-level JSON objects from raw PCK data and merge them.

    PCK data may contain multiple JSON objects concatenated with null-byte
    padding between them.  We split on null runs, then attempt to parse each
    fragment.  Truncated trailing fragments are handled line-by-line.
    """
    merged: dict[str, str] = {}
    chunks = re.split(rb"\x00+", data)
    for chunk in chunks:
        text = chunk.decode("utf-8", errors="replace").strip()
        if not text or not text.startswith("{"):
            continue
        try:
            obj = json.loads(text)
            merged.update(obj)
            continue
        except json.JSONDecodeError:
            pass
        for line in text.split("\n"):
            line = line.strip().rstrip(",")
            if '": "' not in line:
                continue
            try:
                merged.update(json.loads("{" + line + "}"))
            except json.JSONDecodeError:
                pass
    return merged


def _discover_languages(mm: mmap.mmap, search_start: int) -> list[str]:
    """Discover all language codes present in the PCK localization directory."""
    langs: set[str] = set()
    pos = search_start
    while True:
        pos = mm.find(b"localization/", pos)
        if pos == -1:
            break
        mm.seek(pos)
        raw = bytearray()
        for _ in range(100):
            b = mm.read(1)
            if b[0] < 32 or b[0] > 126:
                break
            raw.extend(b)
        path = raw.decode("ascii", errors="replace")
        m = re.match(r"localization/([a-z]{3})/", path)
        if m:
            langs.add(m.group(1))
        pos += 1
    return sorted(langs)


def extract_translations(game_dir: Path) -> dict:
    """Extract all card/relic name translations from the game's PCK file.

    Returns a dict with ``cards`` and ``relics`` keys, each mapping
    entity IDs to ``{lang_code: localized_name}`` dicts.
    """
    pck_path = game_dir / _GAME_PCK
    if not pck_path.exists():
        raise FileNotFoundError(f"{pck_path} not found")

    with open(pck_path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        fsize = mm.size()
        search_start = max(0, fsize - _PCK_INDEX_SEARCH_WINDOW)

        languages = _discover_languages(mm, search_start)

        result: dict[str, dict[str, dict[str, str]]] = {
            "cards": {},
            "relics": {},
        }

        for kind in ("cards", "relics"):
            lang_data: dict[str, dict[str, str]] = {}

            for lang in languages:
                path = f"localization/{lang}/{kind}.json"
                entry = _find_pck_entry(mm, path, search_start)
                if entry is None:
                    continue
                offset, size, flags = entry
                if flags != 0:
                    continue

                mm.seek(offset)
                data = mm.read(size + _PCK_BOUNDARY_BUFFER)
                parsed = _extract_json_objects(data)
                lang_data[lang] = parsed

            all_keys: set[str] = set()
            for ld in lang_data.values():
                all_keys.update(k for k in ld if k.endswith(".title"))

            for key in sorted(all_keys):
                entity_id = key.removesuffix(".title")
                entry_map: dict[str, str] = {}
                for lang, ld in lang_data.items():
                    if key in ld:
                        entry_map[lang] = ld[key]
                if entry_map:
                    result[kind][entity_id] = entry_map

        mm.close()

    return result
