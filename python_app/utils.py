"""
Shared utilities for BoberInSpire.
"""
from __future__ import annotations

import re
from typing import TypeVar

_T = TypeVar("_T")


def strip_bbcode(text: str) -> str:
    return re.sub(r"\[/?[a-z]+(?::\d+)?\]", "", text) if text else ""


def normalize_codex_key(name: str) -> str:
    """Lowercase stripped key for codex dictionaries."""
    return name.lower().strip()


def fuzzy_codex_lookup(db: dict[str, _T], name: str) -> _T | None:
    """
    Exact key match, then substring match either direction (handles short UI labels).
    """
    key = normalize_codex_key(name)
    hit = db.get(key)
    if hit is not None:
        return hit
    for k, val in db.items():
        if key in k or k in key:
            return val
    return None
