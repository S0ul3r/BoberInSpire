"""Extract card & relic name translations from Slay the Spire 2 PCK file.

Usage:
    python scripts/extract_translations.py [--game-dir "C:\\...\\Slay the Spire 2"]

Produces ``data/game_localization/translation_map.json`` with structure::

    {
      "cards": { "ABRASIVE": {"eng": "Abrasive", "rus": "Дикобраз", ...} },
      "relics": { "AKABEKO": {"eng": "Akabeko", "rus": "Акабеко", ...} }
    }
"""
from __future__ import annotations

import argparse
import json
import mmap
import re
import struct
import sys
from pathlib import Path

# Allow running as a standalone script: add parent dir to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from python_app.paths import DATA_DIR, find_game_dir  # noqa: E402

OUT_DIR = DATA_DIR / "game_localization"

# ── PCK parsing constants ────────────────────────────────────────────
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
    # Split on null-byte runs to isolate individual JSON blobs
    chunks = re.split(rb"\x00+", data)
    for chunk in chunks:
        text = chunk.decode("utf-8", errors="replace").strip()
        if not text or not text.startswith("{"):
            continue
        # Try full parse
        try:
            obj = json.loads(text)
            merged.update(obj)
            continue
        except json.JSONDecodeError:
            pass
        # Truncated at boundary — parse line by line
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


def extract(game_dir: Path) -> dict:
    pck_path = game_dir / _GAME_PCK
    if not pck_path.exists():
        print(f"ERROR: {pck_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(pck_path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        fsize = mm.size()

        search_start = max(0, fsize - _PCK_INDEX_SEARCH_WINDOW)

        # Discover available languages
        languages = _discover_languages(mm, search_start)
        print(f"Found languages: {', '.join(languages)}")

        result: dict[str, dict[str, dict[str, str]]] = {
            "cards": {},
            "relics": {},
        }

        for kind in ("cards", "relics"):
            lang_data: dict[str, dict[str, str]] = {}  # lang -> {KEY.title: value}

            for lang in languages:
                path = f"localization/{lang}/{kind}.json"
                entry = _find_pck_entry(mm, path, search_start)
                if entry is None:
                    continue
                offset, size, flags = entry
                if flags != 0:
                    print(f"  {path}: encrypted (flags={flags}), skipping")
                    continue

                mm.seek(offset)
                data = mm.read(size + _PCK_BOUNDARY_BUFFER)
                parsed = _extract_json_objects(data)
                lang_data[lang] = parsed
                titles = {k: v for k, v in parsed.items() if k.endswith(".title")}
                print(f"  {path}: {len(titles)} titles")

            # Build ID-based mapping
            # Collect all .title keys from eng (or any language as fallback)
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

    print(f"\nTotal: {len(result['cards'])} cards, {len(result['relics'])} relics")
    return result


def main():
    parser = argparse.ArgumentParser(description="Extract STS2 translations from PCK")
    parser.add_argument("--game-dir", type=Path, default=None, help="Path to Slay the Spire 2 install directory")
    args = parser.parse_args()

    game_dir = args.game_dir or find_game_dir()
    if game_dir is None:
        print("ERROR: Could not find Slay the Spire 2 install. Use --game-dir.", file=sys.stderr)
        sys.exit(1)

    print(f"Game directory: {game_dir}")
    result = extract(game_dir)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "translation_map.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
