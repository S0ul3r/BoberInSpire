"""Tests for the card reward advisor."""
import pytest

from python_app.reward_advisor import (
    recommend,
    _detect_archetype,
    _count_strikes,
    mobalytics_tier_for,
)


class TestDetectArchetype:
    def test_ironclad_strength(self):
        deck = ["Strike", "Inflame", "Twin Strike", "Defend"]
        assert _detect_archetype("Ironclad", deck, []) == "strength"

    def test_ironclad_exhaust(self):
        deck = ["Corruption", "True Grit", "Body Slam"]
        assert _detect_archetype("Ironclad", deck, []) == "exhaust"

    def test_ironclad_strike(self):
        deck = ["Perfected Strike", "Strike", "Strike", "Strike", "Pommel Strike"]
        assert _detect_archetype("Ironclad", deck, []) == "strike"

    def test_defect_claw(self):
        deck = ["Claw", "Claw", "Scrape"]
        assert _detect_archetype("Defect", deck, []) == "claw"

    def test_silent_shiv(self):
        deck = ["Accuracy", "Cloak and Dagger"]
        assert _detect_archetype("Silent", deck, []) == "shiv"


class TestRecommend:
    def test_ironclad_strength_whirlwind_best(self):
        deck = ["Strike", "Inflame", "Twin Strike", "Defend", "Defend", "Bash"]
        options = ["Whirlwind", "Spite", "Perfected Strike"]
        r = recommend("Ironclad", deck, [], options)
        assert r.best_card == "Whirlwind"
        assert r.archetype == "strength"

    def test_ironclad_strike_perfected_best(self):
        deck = ["Strike", "Strike", "Strike", "Perfected Strike", "Pommel Strike"]
        options = ["Whirlwind", "Spite", "Perfected Strike"]
        r = recommend("Ironclad", deck, [], options)
        assert r.best_card == "Perfected Strike"
        assert r.archetype == "strike"

    def test_empty_options_returns_empty(self):
        r = recommend("Ironclad", ["Strike"], [], [])
        assert r.best_card == ""
        assert len(r.recommendations) == 0

    def test_unknown_character_generic(self):
        r = recommend("Unknown", ["Strike"], [], ["Strike", "Defend"])
        assert len(r.recommendations) == 2
        assert all(rec.score == 50 for rec in r.recommendations)


class TestMobalyticsTiers:
    def test_regent_guiding_star_tier(self):
        assert mobalytics_tier_for("Regent", "Guiding Star") == "B"

    def test_regent_monologue_plus_maps_to_base(self):
        assert mobalytics_tier_for("Regent", "Monologue+") == "D"

    def test_ironclad_offering_is_s(self):
        assert mobalytics_tier_for("Ironclad", "Offering") == "S"

    def test_recommend_regent_prefers_higher_mobalytics_tier(self):
        deck = ["Strike", "Defend", "Defend", "Defend"]
        r = recommend("Regent", deck, [], ["Monologue+", "Guiding Star"])
        assert r.best_card == "Guiding Star"


class TestCountStrikes:
    def test_counts_strike_cards(self):
        assert _count_strikes(["Strike", "Strike", "Perfected Strike", "Defend"]) == 3

    def test_empty_deck(self):
        assert _count_strikes([]) == 0
