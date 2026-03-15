"""
Shared utilities for BoberInSpire.
"""
from __future__ import annotations

import re


def strip_bbcode(text: str) -> str:
    return re.sub(r"\[/?[a-z]+(?::\d+)?\]", "", text) if text else ""
