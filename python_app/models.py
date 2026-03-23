"""
Domain types for exported game snapshots (player, hand, enemies, relics).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Card",
    "Enemy",
    "Relic",
    "PlayerState",
    "MerchantRelic",
    "GameState",
]


@dataclass
class Card:
    name: str
    damage: int
    energy_cost: int
    card_type: str = "attack"
    block: int = 0
    hits: int = 1
    effects: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    id: str = ""

    @property
    def is_attack(self) -> bool:
        return self.card_type == "attack"

    @property
    def strength_scaling(self) -> int:
        return self.effects.get("strength_scaling", 1)


@dataclass
class Enemy:
    name: str
    hp: int
    max_hp: int = 0
    vulnerable_turns: int = 0
    weak_turns: int = 0
    strength: int = 0  # can be negative (e.g. "decreases attack damage by 5")
    poison: int = 0
    intended_move: str = "unknown"
    intended_damage: int = 0
    intended_hits: int = 1
    block: int = 0

    def __post_init__(self):
        if self.max_hp == 0:
            self.max_hp = self.hp

    @property
    def is_vulnerable(self) -> bool:
        return self.vulnerable_turns > 0


@dataclass
class Relic:
    name: str
    rarity: str = "common"
    id: str = ""
    description: str = ""
    effect_type: str = "passive"
    effect_value: dict[str, Any] = field(default_factory=dict)

    @property
    def grants_strength(self) -> int:
        return self.effect_value.get("strength", 0)

    @property
    def grants_vigor(self) -> int:
        return self.effect_value.get("vigor", 0)

    @property
    def applies_vulnerable_all(self) -> int:
        return self.effect_value.get("vulnerable_all", 0)


@dataclass
class PlayerState:
    energy: int = 3
    max_energy: int = 3
    strength: int = 0
    dexterity: int = 0
    vigor: int = 0
    weak_turns: int = 0
    frail_turns: int = 0
    hp: int = 80
    max_hp: int = 80
    block: int = 0
    plating: int = 0  # Block gained at end of turn (reduces block_needed for strategy)


@dataclass
class MerchantRelic:
    name: str
    id: str = ""
    rarity: str = "common"
    cost: int = 0


@dataclass
class GameState:
    player: PlayerState
    hand: list[Card]
    enemies: list[Enemy]
    relics: list[Relic]
    merchant_relics: list[MerchantRelic] = field(default_factory=list)
    turn: int = 1
    draw_pile_count: int = 0
    discard_pile_count: int = 0
    deck: list[str] = field(default_factory=list)
    character: str = "Unknown"
