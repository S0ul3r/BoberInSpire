"""CLI wrapper: extract translations from STS2 PCK and save to JSON.

Usage:
    python scripts/extract_translations.py [--game-dir "C:\\...\\Slay the Spire 2"]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from python_app.paths import DATA_DIR, find_game_dir  # noqa: E402
from python_app.pck_extractor import extract_translations  # noqa: E402

OUT_DIR = DATA_DIR / "game_localization"


def main():
    parser = argparse.ArgumentParser(description="Extract STS2 translations from PCK")
    parser.add_argument("--game-dir", type=Path, default=None,
                        help="Path to Slay the Spire 2 install directory")
    args = parser.parse_args()

    game_dir = args.game_dir or find_game_dir()
    if game_dir is None:
        print("ERROR: Could not find Slay the Spire 2 install. Use --game-dir.", file=sys.stderr)
        sys.exit(1)

    print(f"Game directory: {game_dir}")
    result = extract_translations(game_dir)
    print(f"Extracted: {len(result['cards'])} cards, {len(result['relics'])} relics")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "translation_map.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
