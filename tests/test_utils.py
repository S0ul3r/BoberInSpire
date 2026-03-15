import pytest

from python_app.utils import strip_bbcode


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
