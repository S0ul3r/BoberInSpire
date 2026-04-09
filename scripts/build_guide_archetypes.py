#!/usr/bin/env python3
"""
Generate machine-readable archetype JSON files from markdown guide files.

This keeps `reward_advisor` aligned with `data/build_guides/*/guide.md`.

Run from repo root:
    python scripts/build_guide_archetypes.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_GUIDES_DIR = ROOT / "data" / "build_guides"

FOLDER_TO_CHARACTER: dict[str, str] = {
    "ironclad": "Ironclad",
    "silent": "Silent",
    "defect": "Defect",
    "regent": "Regent",
    "necrobinder": "Necrobinder",
}

ARCHETYPE_KEY_OVERRIDES: dict[tuple[str, str], str] = {
    ("ironclad", "strength build"): "strength",
    ("ironclad", "block build"): "block",
    ("ironclad", "exhaust build"): "exhaust",
    ("ironclad", "bloodletting build"): "bloodletting",
    ("ironclad", "strike build (perfected strike)"): "strike",
    ("silent", "shiv deck"): "shiv",
    ("silent", "poison deck"): "poison",
    ("silent", "sly deck"): "sly",
    ("defect", "claw deck"): "claw",
    ("defect", "simple orb deck"): "orb",
    ("regent", "sovereign blade deck"): "blade",
    ("regent", "star deck"): "star",
    ("necrobinder", "doom deck"): "doom",
    ("necrobinder", "osty deck"): "osty",
}


def _clean_cell_text(text: str) -> str:
    t = text.strip()
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


def _split_names(cell_text: str) -> list[str]:
    """
    Parse table card/relic cells.
    Supports values like:
      "Anchor / Horn Cleat / Permafrost"
      "Iron Club / Nunchaku / Shuriken"
    """
    raw = _clean_cell_text(cell_text)
    if not raw:
        return []
    parts = [p.strip() for p in raw.split("/")]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        key = part.lower()
        if key not in seen:
            seen.add(key)
            out.append(part)
    return out


def _section_chunk(text: str, heading_prefix: str) -> str:
    pat = re.compile(rf"^\s*{re.escape(heading_prefix)}[^\n]*\n", re.MULTILINE)
    m = pat.search(text)
    if not m:
        return ""
    start = m.end()
    # Stop at next H3/H2 within the same archetype block.
    next_heading = re.search(r"^\s*##+\s+.+$", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def _parse_markdown_table_first_col(section_text: str) -> list[str]:
    rows: list[str] = []
    for ln in section_text.splitlines():
        line = ln.strip()
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if not cols:
            continue
        first = cols[0]
        if not first or first.lower() in ("card", "relic"):
            continue
        if set(first) <= {"-"}:
            continue
        rows.extend(_split_names(first))
    return rows


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        k = item.lower().strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(item.strip())
    return out


def _guess_archetype_key(folder: str, title: str) -> str:
    t = title.strip().lower()
    if (folder, t) in ARCHETYPE_KEY_OVERRIDES:
        return ARCHETYPE_KEY_OVERRIDES[(folder, t)]
    t = re.sub(r"\([^)]*\)", "", t).strip()
    t = t.replace(" deck", "").replace(" build", "").strip()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t or "generic"


def _parse_guide_markdown(folder: str, text: str) -> dict[str, dict[str, list[str]]]:
    arch_headings = list(
        re.finditer(r"^\s*##\s+Archetype\s+\d+:\s+(.+?)\s*$", text, re.MULTILINE)
    )
    result: dict[str, dict[str, list[str]]] = {}
    for i, m in enumerate(arch_headings):
        title = m.group(1).strip()
        start = m.end()
        end = arch_headings[i + 1].start() if i + 1 < len(arch_headings) else len(text)
        block = text[start:end]
        key = _guess_archetype_key(folder, title)
        early = _parse_markdown_table_first_col(_section_chunk(block, "### Early Game Priorities"))
        mid = _parse_markdown_table_first_col(_section_chunk(block, "### Mid Game Priorities"))
        high = _parse_markdown_table_first_col(
            _section_chunk(block, "### High-Commitment / Payoff Cards")
        )
        relics = _parse_markdown_table_first_col(_section_chunk(block, "### Relic Priorities"))
        signals = _dedupe((early[:2] + mid[:2] + high[:1]))
        result[key] = {
            "title": [title],
            "signals": _dedupe(signals),
            "early": _dedupe(early),
            "mid": _dedupe(mid),
            "high": _dedupe(high),
            "relics": _dedupe(relics),
        }
    return result


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for folder in sorted(FOLDER_TO_CHARACTER):
        guide_path = BUILD_GUIDES_DIR / folder / "guide.md"
        if not guide_path.is_file():
            print(f"Skip {folder}: missing {guide_path}")
            continue
        text = guide_path.read_text(encoding="utf-8")
        archetypes = _parse_guide_markdown(folder, text)
        payload = {
            "source": str(guide_path.relative_to(ROOT)).replace("\\", "/"),
            "character": FOLDER_TO_CHARACTER[folder],
            "generated_at": now,
            "note": "Generated by scripts/build_guide_archetypes.py from guide.md.",
            "archetypes": archetypes,
        }
        out_path = BUILD_GUIDES_DIR / folder / "guide_archetypes.json"
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {out_path} ({len(archetypes)} archetypes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
