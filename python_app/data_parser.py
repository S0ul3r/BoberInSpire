from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Card, Enemy, GameState, MerchantRelic, PlayerState, Relic
from .card_db import enrich_card_description
from .relic_db import enrich_relic_description
from .translator import to_english, to_english_list


class ParseError(Exception):
    """Raised when combat / snapshot JSON cannot be mapped to ``GameState``."""


def _parse_card(raw: dict[str, Any]) -> Card:
    """Parse a card from the mod JSON. damage/block/energy_cost/hits come from the game
    (DynamicVars and current cost) and should reflect upgrades, Strength, relics like Tezcatara's Ember."""
    name = to_english(raw["name"])
    desc = raw.get("description", "")
    if not desc:
        desc = enrich_card_description(name)
    return Card(
        name=name,
        damage=raw.get("damage", 0),
        energy_cost=raw.get("energy_cost", 0),
        card_type=raw.get("card_type", "attack" if raw.get("damage", 0) > 0 else "skill"),
        block=raw.get("block", 0),
        hits=raw.get("hits", 1),
        effects=raw.get("effects", {}),
        description=desc,
        id=raw.get("id", ""),
    )


def _parse_enemy(raw: dict[str, Any]) -> Enemy:
    return Enemy(
        name=raw["name"],
        hp=raw["hp"],
        max_hp=raw.get("max_hp", raw["hp"]),
        vulnerable_turns=raw.get("vulnerable_turns", 0),
        weak_turns=raw.get("weak_turns", 0),
        strength=raw.get("strength", 0),
        poison=raw.get("poison", 0),
        intended_move=raw.get("intended_move", "unknown"),
        intended_damage=raw.get("intended_damage", 0),
        intended_hits=raw.get("intended_hits", 1),
        block=raw.get("block", 0),
    )


def _parse_relic(raw: dict[str, Any]) -> Relic:
    name = to_english(raw["name"])
    desc = raw.get("description", "")
    if not desc:
        desc = enrich_relic_description(name)
    return Relic(
        name=name,
        rarity=raw.get("rarity", "common"),
        id=raw.get("id", ""),
        description=desc,
        effect_type=raw.get("effect_type", "passive"),
        effect_value=raw.get("effect_value", {}),
    )


def _parse_player(raw: dict[str, Any]) -> PlayerState:
    return PlayerState(
        energy=raw.get("energy", 3),
        max_energy=raw.get("max_energy", raw.get("energy", 3)),
        strength=raw.get("strength", 0),
        dexterity=raw.get("dexterity", 0),
        vigor=raw.get("vigor", 0),
        weak_turns=raw.get("weak_turns", 0),
        frail_turns=raw.get("frail_turns", 0),
        hp=raw.get("hp", 80),
        max_hp=raw.get("max_hp", 80),
        block=raw.get("block", 0),
        plating=raw.get("plating", 0),
    )


def _parse_merchant_relic(raw: dict[str, Any]) -> MerchantRelic:
    return MerchantRelic(
        name=to_english(raw.get("name", "?")),
        id=raw.get("id", ""),
        rarity=raw.get("rarity", "common"),
        cost=raw.get("cost", 0),
    )


def parse_game_state(data: dict[str, Any]) -> GameState:
    """Parse a raw JSON dict into a validated GameState."""
    try:
        player = _parse_player(data.get("player", {}))
        hand = [_parse_card(c) for c in data.get("hand", [])]
        enemies = [_parse_enemy(e) for e in data.get("enemies", [])]
        relics = [_parse_relic(r) for r in data.get("relics", [])]
        merchant_relics = [
            _parse_merchant_relic(mr)
            for mr in data.get("merchant_relics") or []
        ]
    except (KeyError, TypeError) as exc:
        raise ParseError(f"Invalid game state JSON: {exc}") from exc

    return GameState(
        player=player,
        hand=hand,
        enemies=enemies,
        relics=relics,
        merchant_relics=merchant_relics,
        turn=data.get("turn", 1),
        draw_pile_count=data.get("draw_pile_count", 0),
        discard_pile_count=data.get("discard_pile_count", 0),
        deck=to_english_list(data.get("deck") or []),
        character=data.get("character", "Unknown"),
    )


def load_game_state(path: str | Path) -> GameState:
    """Load and parse a game state JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Game state file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return parse_game_state(data)


def parse_reward_state(data: dict[str, Any]) -> dict[str, Any]:
    """Parse card reward screen JSON from the mod. Returns dict with character, deck, relics, options."""
    if not isinstance(data, dict):
        return {}
    return {
        "type": data.get("type", "card_reward"),
        "character": data.get("character", "Unknown"),
        "deck": to_english_list(data.get("deck") or []),
        "relics": to_english_list(data.get("relics") or []),
        "options": to_english_list(data.get("options") or []),
    }


def load_reward_state(path: str | Path) -> dict[str, Any]:
    """Load and parse reward state JSON file."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not data or not isinstance(data, dict):
            return {}
        return parse_reward_state(data)
    except (json.JSONDecodeError, OSError):
        return {}
