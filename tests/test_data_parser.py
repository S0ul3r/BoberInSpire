import json
import tempfile
from pathlib import Path

import pytest

from python_app.data_parser import load_game_state, parse_game_state, ParseError
from python_app.models import Card, Enemy, PlayerState


MINIMAL_STATE = {
    "player": {"energy": 3, "strength": 1},
    "hand": [
        {"name": "Strike", "damage": 6, "energy_cost": 1},
    ],
    "enemies": [
        {"name": "Cultist", "hp": 40},
    ],
    "relics": [],
    "turn": 1,
}

FULL_STATE = {
    "player": {
        "energy": 3,
        "max_energy": 3,
        "strength": 2,
        "dexterity": 1,
        "vigor": 0,
        "weak_turns": 0,
        "hp": 65,
        "max_hp": 80,
        "block": 5,
    },
    "hand": [
        {"name": "Strike", "damage": 6, "energy_cost": 1, "card_type": "attack"},
        {"name": "Defend", "damage": 0, "block": 5, "energy_cost": 1, "card_type": "skill"},
        {
            "name": "Heavy Blade",
            "damage": 14,
            "energy_cost": 2,
            "card_type": "attack",
            "effects": {"strength_scaling": 3},
        },
    ],
    "enemies": [
        {
            "name": "Jaw Worm",
            "hp": 32,
            "max_hp": 44,
            "vulnerable_turns": 2,
            "weak_turns": 0,
            "intended_move": "attack",
            "intended_damage": 11,
        },
    ],
    "relics": [
        {
            "name": "Akabeko",
            "rarity": "common",
            "effect_type": "combat_start",
            "effect_value": {"vigor": 8},
        },
    ],
    "turn": 1,
}


class TestParseGameState:
    def test_minimal_state(self):
        gs = parse_game_state(MINIMAL_STATE)
        assert gs.player.energy == 3
        assert gs.player.strength == 1
        assert len(gs.hand) == 1
        assert gs.hand[0].name == "Strike"
        assert len(gs.enemies) == 1
        assert gs.enemies[0].name == "Cultist"

    def test_full_state(self):
        gs = parse_game_state(FULL_STATE)
        assert gs.player.hp == 65
        assert gs.player.max_hp == 80
        assert gs.player.dexterity == 1
        assert gs.player.block == 5
        assert len(gs.hand) == 3
        assert gs.hand[2].effects["strength_scaling"] == 3
        assert gs.enemies[0].vulnerable_turns == 2
        assert gs.relics[0].name == "Akabeko"
        assert gs.relics[0].grants_vigor == 8

    def test_card_type_auto_detection(self):
        gs = parse_game_state(MINIMAL_STATE)
        assert gs.hand[0].card_type == "attack"
        assert gs.hand[0].is_attack is True

    def test_skill_card(self):
        gs = parse_game_state(FULL_STATE)
        defend = gs.hand[1]
        assert defend.card_type == "skill"
        assert defend.is_attack is False
        assert defend.block == 5

    def test_enemy_max_hp_defaults_to_hp(self):
        gs = parse_game_state(MINIMAL_STATE)
        assert gs.enemies[0].max_hp == 40

    def test_missing_hand_card_name_raises(self):
        bad = {
            "player": {"energy": 3},
            "hand": [{"damage": 6}],
            "enemies": [],
        }
        with pytest.raises(ParseError):
            parse_game_state(bad)

    def test_empty_state(self):
        gs = parse_game_state({})
        assert gs.player.energy == 3
        assert gs.hand == []
        assert gs.enemies == []


class TestLoadGameState:
    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(MINIMAL_STATE, f)
            f.flush()
            gs = load_game_state(f.name)

        assert gs.hand[0].name == "Strike"
        Path(f.name).unlink()

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_game_state("nonexistent_file_xyz.json")


class TestParseGameStateMerchantRelics:
    def test_merchant_relics_parsed(self):
        state_dict = {
            **MINIMAL_STATE,
            "merchant_relics": [
                {"name": "Relic A", "rarity": "rare", "cost": 150},
                {"name": "Relic B", "id": "xyz", "cost": 99},
            ],
        }
        gs = parse_game_state(state_dict)
        assert len(gs.merchant_relics) == 2
        assert gs.merchant_relics[0].name == "Relic A"
        assert gs.merchant_relics[0].rarity == "rare"
        assert gs.merchant_relics[0].cost == 150
        assert gs.merchant_relics[1].name == "Relic B"
        assert gs.merchant_relics[1].cost == 99

    def test_merchant_relics_default_empty(self):
        gs = parse_game_state(MINIMAL_STATE)
        assert gs.merchant_relics == []


class TestParseErrors:
    def test_missing_enemy_name_raises(self):
        bad = {
            "player": {"energy": 3},
            "hand": [],
            "enemies": [{"hp": 30}],
        }
        with pytest.raises(ParseError):
            parse_game_state(bad)

    def test_invalid_hand_type_raises(self):
        bad = {"player": {}, "hand": "not a list", "enemies": []}
        with pytest.raises(ParseError):
            parse_game_state(bad)
