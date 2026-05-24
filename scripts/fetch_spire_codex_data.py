#!/usr/bin/env python3
"""
Download card/relic snapshots from Spire Codex (GitHub) into data/.

Preserves curated short_description on relics when the full description is unchanged
(e.g. after a patch that only reworded other relics).

Source: https://github.com/ptrlrd/spire-codex (data/cards.json, data/relics.json)

Usage (repo root):
    python scripts/fetch_spire_codex_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CARDS_URL = "https://raw.githubusercontent.com/ptrlrd/spire-codex/main/data/cards.json"
RELICS_URL = "https://raw.githubusercontent.com/ptrlrd/spire-codex/main/data/relics.json"
MECHANICS_URL = (
    "https://raw.githubusercontent.com/ptrlrd/spire-codex/main/data/mechanics_constants.json"
)

OUT_CARDS = DATA / "spire_codex_cards.json"
OUT_RELICS = DATA / "spire_codex_relics.json"
OUT_BUFFS = DATA / "buffs_debuffs.json"

CARD_FIELDS = ("id", "name", "description", "type", "cost", "rarity", "color")
RELIC_FIELDS = ("id", "name", "description", "rarity", "pool", "short_description")


def fetch_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 BoberInSpire-codex-fetch/1.0"})
    with urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_existing_relics() -> dict[str, dict]:
    if not OUT_RELICS.is_file():
        return {}
    try:
        rows = json.loads(OUT_RELICS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(rows, list):
        return {}
    return {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")}


def slim_cards(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for entry in raw:
        row = {k: entry.get(k, "") for k in CARD_FIELDS}
        out.append(row)
    out.sort(key=lambda r: r["id"])
    return out


def slim_relics(raw: list[dict], previous: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    kept_short = 0
    for entry in raw:
        row = {k: entry.get(k, "") for k in RELIC_FIELDS}
        old = previous.get(row["id"])
        if old:
            old_short = (old.get("short_description") or "").strip()
            if old.get("description") == row.get("description") and old_short:
                row["short_description"] = old["short_description"]
                kept_short += 1
        out.append(row)
    out.sort(key=lambda r: r["id"])
    if kept_short:
        print(f"Kept {kept_short} curated short_description values (description unchanged)")
    return out


def sync_buff_multipliers(buffs_path: Path, mechanics: dict) -> bool:
    """Update Vulnerable/Weak/Frail multipliers from mechanics_constants when present."""
    combat = mechanics.get("combat_modifiers") or {}
    if not combat or not buffs_path.is_file():
        return False

    with open(buffs_path, encoding="utf-8") as f:
        buffs = json.load(f)

    debuffs = buffs.get("debuffs") or {}
    changed = False
    for name, field in (
        ("Vulnerable", "damage_multiplier"),
        ("Weak", "damage_multiplier"),
        ("Frail", "block_multiplier"),
    ):
        mod = combat.get(name)
        if not mod or name not in debuffs:
            continue
        value = mod.get("value")
        if value is None:
            continue
        if debuffs[name].get(field) != value:
            debuffs[name][field] = value
            changed = True

    if changed:
        with open(buffs_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(buffs, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return changed


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    try:
        raw_cards = fetch_json(CARDS_URL)
        raw_relics = fetch_json(RELICS_URL)
        mechanics = fetch_json(MECHANICS_URL)
    except OSError as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1

    if not isinstance(raw_cards, list) or not isinstance(raw_relics, list):
        print("Unexpected Spire Codex payload shape.", file=sys.stderr)
        return 1

    previous_relics = load_existing_relics()
    cards = slim_cards(raw_cards)
    relics = slim_relics(raw_relics, previous_relics)
    write_json(OUT_CARDS, cards)
    write_json(OUT_RELICS, relics)

    buffs_changed = False
    if isinstance(mechanics, dict):
        buffs_changed = sync_buff_multipliers(OUT_BUFFS, mechanics)

    print(f"Wrote {OUT_CARDS} ({len(cards)} cards)")
    print(f"Wrote {OUT_RELICS} ({len(relics)} relics)")
    if buffs_changed:
        print(f"Updated combat multipliers in {OUT_BUFFS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
