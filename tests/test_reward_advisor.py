"""Tests for the card reward advisor."""

from python_app.reward_advisor import (
    recommend,
    _detect_archetype,
    _count_strikes,
    mobalytics_tier_for,
    wiki_tier_for,
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

    def test_upgraded_offered_card_gets_flat_score_bonus(self):
        """Reward rows ending with '+' get +10 on the final blended score (capped at 100)."""
        deck = ["Strike", "Defend", "Inflame", "Twin Strike"]
        r = recommend("Ironclad", deck, [], ["Twin Strike", "Twin Strike+"])
        base = next(x for x in r.recommendations if x.name == "Twin Strike")
        plus = next(x for x in r.recommendations if x.name == "Twin Strike+")
        assert plus.score == min(100, base.score + 10)
        assert "upgraded offer" in plus.reason.lower()

    def test_empty_options_returns_empty(self):
        r = recommend("Ironclad", ["Strike"], [], [])
        assert r.best_card == ""
        assert len(r.recommendations) == 0

    def test_unknown_character_generic(self):
        r = recommend("Unknown", ["Strike"], [], ["Strike", "Defend"])
        assert len(r.recommendations) == 2
        assert all(rec.score == 50 for rec in r.recommendations)
        assert "No build match, score comes from tier lists" in r.recommendations[0].reason

    def test_neutral_ironclad_compact_reason(self):
        """Neutral picks get a short subtitle, not long debug prose."""
        deck = ["Corruption", "True Grit"]  # exhaust signals but low count → still exhaust archetype
        r = recommend("Ironclad", deck, [], ["Whirlwind", "Inflame"])
        for rec in r.recommendations:
            assert "Neutral pick" not in rec.reason
            assert "list avg blended" not in rec.reason.lower()
            assert "unique names in export" not in rec.reason
            assert len(rec.reason.strip()) > 10


class TestSts2WikiTiers:
    def test_silent_snakebite_is_f(self):
        assert wiki_tier_for("Silent", "Snakebite") == "F"

    def test_expect_a_fight_matches_wiki_casing(self):
        assert wiki_tier_for("Ironclad", "Expect a Fight") == "S"


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


class TestCoopCharacterCoercion:
    def test_regent_export_ironclad_offers_use_ironclad_tiers(self):
        deck = ["Strike", "Defend"]
        options = ["Impervious", "Second Wind", "Uppercut"]
        r = recommend("Regent", deck, [], options)
        assert any(rec.mobalytics_tier is not None for rec in r.recommendations)
        assert not all(rec.score == 50 for rec in r.recommendations)


class TestWikiBuildGuides:
    """slaythespire-2.com scraped builds under data/build_guides/<char>/wiki_builds.json."""

    def test_strength_deck_sets_wiki_build_title(self):
        deck = [
            "Inflame",
            "Demon Form",
            "Offering",
            "Twin Strike",
            "Strike",
            "Defend",
            "Bash",
        ]
        r = recommend("Ironclad", deck, [], ["Clash", "Anger"])
        assert r.wiki_build_title
        assert "Strength" in r.wiki_build_title

    def test_heavy_blade_pref_when_wiki_strength_fit(self):
        deck = ["Inflame", "Demon Form", "Offering", "Twin Strike", "Strike"]
        r = recommend("Ironclad", deck, [], ["Heavy Blade", "Clash"])
        assert r.best_card == "Heavy Blade"
        hb = next(x for x in r.recommendations if x.name == "Heavy Blade")
        assert "slaythespire-2.com" in hb.reason.lower()

    def test_starter_only_no_wiki_fit(self):
        r = recommend("Ironclad", ["Strike", "Strike", "Defend", "Defend"], [], ["Inflame", "Bash"])
        assert r.wiki_build_title is None


class TestCountStrikes:
    def test_counts_strike_cards(self):
        assert _count_strikes(["Strike", "Strike", "Perfected Strike", "Defend"]) == 3

    def test_empty_deck(self):
        assert _count_strikes([]) == 0
