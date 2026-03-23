import pytest

from python_app.utils import fuzzy_codex_lookup, normalize_codex_key, strip_bbcode


class TestStripBbcode:
    def test_removes_gold_tags(self):
        assert strip_bbcode("[gold]Rare Card[/gold]") == "Rare Card"

    def test_removes_energy_tags(self):
        assert strip_bbcode("Gain [energy:1]") == "Gain "

    def test_handles_empty(self):
        assert strip_bbcode("") == ""

    def test_handles_none_like_empty(self):
        assert strip_bbcode("") == ""

    def test_leaves_plain_text(self):
        assert strip_bbcode("Draw 3 cards") == "Draw 3 cards"


class TestCodexLookup:
    def test_normalize_codex_key(self):
        assert normalize_codex_key("  Bash ") == "bash"

    def test_fuzzy_codex_exact(self):
        db = {"bash": {"name": "Bash"}}
        assert fuzzy_codex_lookup(db, "Bash") == {"name": "Bash"}

    def test_fuzzy_codex_substring(self):
        db = {"pommel strike": {"id": "1"}}
        assert fuzzy_codex_lookup(db, "Pommel") == {"id": "1"}
