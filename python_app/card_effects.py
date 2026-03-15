"""
Parse card descriptions to extract combat-relevant effects: draw, debuffs, AOE.
Used by the strategy engine to consider draw cards, Weak/Vulnerable/Poison, and multi-target damage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .card_db import lookup_card
from .utils import strip_bbcode


@dataclass
class CardEffects:
    """Parsed effects from a card's description."""
    draw: int = 0
    applies_weak: int = 0
    applies_vulnerable: int = 0
    applies_poison: int = 0
    applies_frail: int = 0
    is_aoe: bool = False
    aoe_damage: int = 0
    gains_energy: int = 0
    is_power: bool = False
    # Buffs granted to player
    grants_strength: int = 0
    grants_dexterity: int = 0
    grants_vigor: int = 0
    grants_intangible: int = 0
    grants_plating: int = 0
    grants_thorns: int = 0
    grants_buffer: int = 0
    grants_block_next_turn: int = 0
    grants_draw_next_turn: int = 0
    grants_energy_next_turn: int = 0
    grants_retain_hand: bool = False
    # Card modifiers
    exhausts_self: bool = False
    exhausts_other: bool = False
    ethereal: bool = False
    innate: bool = False
    has_sly: bool = False
    causes_discard: int = 0
    adds_random_attack: int = 0
    # "Next X you play costs 0" / "Skills cost 0" (Corruption) – applied after playing this card
    next_skill_cost_zero: bool = False
    next_attack_cost_zero: bool = False
    next_power_cost_zero: bool = False
    next_ethereal_cost_zero: bool = False
    all_skills_cost_zero: bool = False


DISCARD_ALL_HAND = 10


def parse_card_effects(card_name: str, card_type: str = "", description: str = "") -> CardEffects:
    """
    Parse card effects from codex description. Uses card_db if description empty.
    """
    if not description:
        info = lookup_card(card_name)
        if info:
            description = info.get("description", "")
        else:
            return CardEffects()
    desc = strip_bbcode(description).replace("\n", " ")
    desc_lower = desc.lower()

    effects = CardEffects()
    effects.is_power = (card_type or "").lower() == "power"

    # Draw: "Draw 3 cards" or "draw 2 cards"
    m = re.search(r"draw\s+(\d+)\s+cards?", desc_lower, re.I)
    if m:
        effects.draw = int(m.group(1))

    # Apply Weak: "Apply 1 Weak" or "1 Weak" or "apply X Weak to ALL"
    m = re.search(r"apply\s+(\d+)\s+weak", desc_lower, re.I)
    if m:
        effects.applies_weak = int(m.group(1))
    elif re.search(r"\d+\s+weak", desc_lower) or "weak" in desc_lower and "apply" in desc_lower:
        m = re.search(r"(\d+)\s+weak", desc_lower, re.I)
        effects.applies_weak = int(m.group(1)) if m else 1

    # Apply Vulnerable
    m = re.search(r"apply\s+(\d+)\s+vulnerable", desc_lower, re.I)
    if m:
        effects.applies_vulnerable = int(m.group(1))
    elif re.search(r"\d+\s+vulnerable", desc_lower):
        m = re.search(r"(\d+)\s+vulnerable", desc_lower, re.I)
        effects.applies_vulnerable = int(m.group(1)) if m else 1

    # Apply Poison: "Apply 3 Poison" or "3 Poison" or "apply X Poison to ALL"
    m = re.search(r"apply\s+(\d+)\s+poison", desc_lower, re.I)
    if m:
        effects.applies_poison = int(m.group(1))
    else:
        m = re.search(r"(\d+)\s+poison", desc_lower, re.I)
        if m:
            effects.applies_poison = int(m.group(1))

    # AOE damage: "Deal X damage to ALL enemies" or "X damage to ALL"
    if "to all" in desc_lower or "all enemies" in desc_lower:
        effects.is_aoe = True
        m = re.search(r"deal\s+(\d+)\s+damage", desc_lower, re.I)
        if m:
            effects.aoe_damage = int(m.group(1))
        else:
            m = re.search(r"(\d+)\s+damage\s+to\s+all", desc_lower, re.I)
            if m:
                effects.aoe_damage = int(m.group(1))

    # Gain energy (this turn)
    m = re.search(r"gain\s+\[energy:(\d+)\]", desc_lower, re.I)
    if m:
        effects.gains_energy = int(m.group(1))
    else:
        m = re.search(r"gain\s+(\d+)\s+energy", desc_lower, re.I)
        if m:
            effects.gains_energy = int(m.group(1))

    # Apply Frail (to enemy)
    m = re.search(r"apply\s+(\d+)\s+frail", desc_lower, re.I)
    if m:
        effects.applies_frail = int(m.group(1))
    elif "frail" in desc_lower and re.search(r"(\d+)\s+frail", desc_lower, re.I):
        m = re.search(r"(\d+)\s+frail", desc_lower, re.I)
        effects.applies_frail = int(m.group(1)) if m else 1

    # Buffs: Strength, Dexterity, Vigor (Gain X ...)
    m = re.search(r"gain\s+(\d+)\s+strength", desc_lower, re.I)
    if m:
        effects.grants_strength = int(m.group(1))
    m = re.search(r"gain\s+(\d+)\s+dexterity", desc_lower, re.I)
    if m:
        effects.grants_dexterity = int(m.group(1))
    m = re.search(r"gain\s+(\d+)\s+vigor", desc_lower, re.I)
    if m:
        effects.grants_vigor = int(m.group(1))
    m = re.search(r"gain\s+(\d+)\s+intangible", desc_lower, re.I)
    if m:
        effects.grants_intangible = int(m.group(1))
    elif "intangible" in desc_lower and "gain" in desc_lower:
        effects.grants_intangible = 1
    m = re.search(r"gain\s+(\d+)\s+plating", desc_lower, re.I)
    if m:
        effects.grants_plating = int(m.group(1))
    m = re.search(r"gain\s+(\d+)\s+thorns", desc_lower, re.I)
    if m:
        effects.grants_thorns = int(m.group(1))
    m = re.search(r"gain\s+(\d+)\s+buffer", desc_lower, re.I)
    if m:
        effects.grants_buffer = int(m.group(1))
    elif "buffer" in desc_lower and "gain" in desc_lower:
        effects.grants_buffer = 1

    # Next-turn effects
    if "next turn" in desc_lower:
        m = re.search(r"next turn[^.]*gain\s+(\d+)\s+block", desc_lower, re.I)
        if m:
            effects.grants_block_next_turn = int(m.group(1))
        m = re.search(r"gain\s+(\d+)\s+block[^.]*next turn", desc_lower, re.I)
        if m:
            effects.grants_block_next_turn = int(m.group(1))
        m = re.search(r"next turn[^.]*gain\s+\[energy:(\d+)\]", desc_lower, re.I)
        if m:
            effects.grants_energy_next_turn = int(m.group(1))
        m = re.search(r"next turn[^.]*gain\s+(\d+)\s+energy", desc_lower, re.I)
        if m:
            effects.grants_energy_next_turn = int(m.group(1))
        m = re.search(r"next turn[^.]*draw\s+(\d+)", desc_lower, re.I)
        if m:
            effects.grants_draw_next_turn = int(m.group(1))
    if "retain" in desc_lower and "hand" in desc_lower:
        effects.grants_retain_hand = True

    # Card modifiers: Exhaust (other = target other cards; self = this card exhausts)
    if re.search(r"exhaust\s+(?:\d+|your|1\s+card|up to|the)", desc_lower, re.I):
        effects.exhausts_other = True
    if not effects.exhausts_other and "exhaust" in desc_lower:
        effects.exhausts_self = True
    if "ethereal" in desc_lower:
        effects.ethereal = True
    if "innate" in desc_lower:
        effects.innate = True
    if "sly" in desc_lower:
        effects.has_sly = True

    m = re.search(r"discard\s+your\s+hand", desc_lower, re.I)
    if m:
        effects.causes_discard = DISCARD_ALL_HAND
    else:
        m = re.search(r"discard\s+(\d+)\s+cards?", desc_lower, re.I)
        if m:
            effects.causes_discard = int(m.group(1))
        elif re.search(r"discard\s+1\s+card", desc_lower, re.I):
            effects.causes_discard = 1

    # Add random Attack(s) into your Hand when you play this card (Infernal Blade, Splash).
    # Excludes: Powers (e.g. "Whenever you play an Attack, add..."), and "Add N into Draw Pile" (Metamorphosis).
    is_power = (card_type or "").lower() == "power"
    if not is_power:
        if re.search(r"add\s+a\s+random\s+attack\s+into\s+your\s+hand", desc_lower, re.I):
            effects.adds_random_attack = 1
        else:
            m = re.search(r"add\s+(\d+)\s+random\s+attacks?\s+into\s+your\s+hand", desc_lower, re.I)
            if m:
                effects.adds_random_attack = int(m.group(1))
            elif re.search(r"choose\s+1\s+of\s+\d+\s+random\s+attacks?.*(?:into\s+your\s+hand|to\s+add\s+into\s+your\s+hand)", desc_lower, re.I):
                effects.adds_random_attack = 1

    # "Next X you play costs 0 [energy:1]" / "costs 0" – cost reduction for next card of type
    if re.search(r"next\s+skill\s+you\s+play\s+costs\s+0", desc_lower, re.I):
        effects.next_skill_cost_zero = True
    if re.search(r"next\s+attack\s+you\s+play\s+costs\s+0", desc_lower, re.I):
        effects.next_attack_cost_zero = True
    if re.search(r"next\s+power\s+you\s+play\s+costs\s+0", desc_lower, re.I):
        effects.next_power_cost_zero = True
    if re.search(r"next\s+(?:\[gold\]\s*)?ethereal(?:\s*\[/gold\])?\s+card\s+you\s+play\s+costs\s+0", desc_lower, re.I):
        effects.next_ethereal_cost_zero = True
    if re.search(r"next\s+.*?ethereal.*?costs\s+0", desc_lower, re.I):
        effects.next_ethereal_cost_zero = True
    # "Skills cost 0" (Corruption – all skills this turn after playing)
    if re.search(r"skills\s+cost\s+0", desc_lower, re.I):
        effects.all_skills_cost_zero = True

    return effects
