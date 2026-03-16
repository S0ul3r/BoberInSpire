"""
Turn strategy: suggested card play order based on hand, incoming damage, and block/kill logic.
Uses game-exported card data (damage, energy_cost, block) so strategy reflects current state
(Tezcatara's Ember, Strength, upgrades, etc.).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .card_effects import parse_card_effects
from .combat_engine import calculate_incoming_damage, compute_card_block
from .models import Card, GameState


VULNERABLE_MULTIPLIER = 1.5
WEAK_DAMAGE_MULTIPLIER = 0.75
WEAK_BLOCK_REDUCTION = 0.75
MIN_ENERGY_FOR_SORT = 0.5
RANDOM_ATTACK_DAMAGE_ESTIMATE = 12


@dataclass
class CardSuggestion:
    """One card in the recommended play plan."""
    name: str
    role: str
    value: int
    energy_cost: int


@dataclass
class StrategySuggestion:
    """Full turn strategy computed from hand + incoming damage."""
    incoming_damage: int
    current_block: int
    block_needed: int

    suggested_cards: list[CardSuggestion]
    total_block_gain: int
    total_damage: int
    energy_used: int
    energy_remaining: int

    block_surplus: int
    damage_surplus: int
    is_safe: bool
    any_lethal: list[str]
    prioritize_kill: bool = False


def _effective_damage(card: Card, strength: int, vigor: int,
                      is_weak: bool, vuln_enemies: bool) -> int:
    """Quick damage estimate for sorting; doesn't consume vigor."""
    if not card.is_attack:
        return 0
    base = card.damage + strength + vigor
    if is_weak:
        base = math.floor(base * WEAK_DAMAGE_MULTIPLIER)
    if vuln_enemies:
        base = math.floor(base * VULNERABLE_MULTIPLIER)
    return max(base, 0) * max(card.hits, 1)


def _effective_energy_cost(card: Card, cost_buffs: dict[str, bool]) -> int:
    """Cost to pay for this card after 'next X costs 0' / 'Skills cost 0' buffs."""
    if cost_buffs.get("all_skills_0") and card.card_type == "skill":
        return 0
    if cost_buffs.get("next_skill_0") and card.card_type == "skill":
        return 0
    if cost_buffs.get("next_attack_0") and card.is_attack:
        return 0
    if cost_buffs.get("next_power_0") and card.card_type == "power":
        return 0
    if cost_buffs.get("next_ethereal_0"):
        eff = parse_card_effects(card.name, card.card_type, card.description)
        if eff.ethereal or "ethereal" in (card.description or "").lower():
            return 0
    return card.energy_cost


def compute_strategy(state: GameState) -> StrategySuggestion:
    """
    Solve: given incoming damage, pick cards in optimal order.
    Uses card.energy_cost and card.damage/block from game export (current values).
    """
    incoming = calculate_incoming_damage(state)
    energy = state.player.energy
    dex = state.player.dexterity
    strength = state.player.strength
    vigor = state.player.vigor
    is_weak = state.player.weak_turns > 0
    num_enemies = len(state.enemies)

    any_vuln = any(e.is_vulnerable for e in state.enemies)

    effective_block = state.player.block + state.player.plating
    block_needed = max(incoming.total_incoming - effective_block, 0)

    block_cards: list[tuple[int, Card, int]] = []
    attack_cards: list[tuple[int, Card, int]] = []
    draw_cards: list[tuple[int, Card, int]] = []
    add_attack_cards: list[tuple[int, Card, int]] = []
    debuff_cards: list[tuple[int, Card, str, int]] = []
    poison_cards: list[tuple[int, Card, int]] = []
    aoe_cards: list[tuple[int, Card, int]] = []
    defensive_buff_cards: list[tuple[int, Card, int]] = []
    setup_cards: list[tuple[int, Card, int]] = []
    discard_cards: list[tuple[int, Card, int]] = []
    hand_has_sly = False

    for i, card in enumerate(state.hand):
        eff = parse_card_effects(card.name, card.card_type, card.description)

        if eff.draw > 0:
            draw_cards.append((i, card, eff.draw))
        if eff.adds_random_attack > 0:
            add_attack_cards.append((i, card, eff.adds_random_attack * RANDOM_ATTACK_DAMAGE_ESTIMATE))
        if eff.has_sly:
            hand_has_sly = True
        if eff.causes_discard > 0:
            discard_cards.append((i, card, eff.causes_discard))
        if eff.applies_weak > 0:
            debuff_cards.append((i, card, "weak", eff.applies_weak))
        if eff.applies_vulnerable > 0:
            debuff_cards.append((i, card, "vulnerable", eff.applies_vulnerable))
        if eff.applies_poison > 0 and not (card.is_attack or (eff.is_aoe and eff.aoe_damage > 0)):
            poison_cards.append((i, card, eff.applies_poison))
        if eff.is_aoe and eff.aoe_damage > 0:
            fake = Card(card.name, eff.aoe_damage, card.energy_cost, card.card_type)
            aoe_dmg = _effective_damage(fake, strength, vigor, is_weak, any_vuln)
            aoe_cards.append((i, card, aoe_dmg))
        if card.is_attack and not (eff.is_aoe and eff.aoe_damage > 0):
            dmg = _effective_damage(card, strength, vigor, is_weak, any_vuln)
            attack_cards.append((i, card, dmg))
        if card.block > 0:
            blk = compute_card_block(card, dex, is_frail=state.player.frail_turns > 0)
            block_cards.append((i, card, blk))
        if (
            card.block <= 0
            and not card.is_attack
            and eff.draw <= 0
            and eff.applies_weak <= 0
            and eff.applies_vulnerable <= 0
            and not (eff.is_aoe and eff.aoe_damage > 0)
            and (eff.applies_poison <= 0 or (eff.applies_poison > 0 and (card.is_attack or (eff.is_aoe and eff.aoe_damage > 0))))
        ):
            if eff.grants_intangible or eff.grants_plating or eff.grants_buffer or eff.grants_thorns:
                val = eff.grants_intangible + eff.grants_plating + eff.grants_buffer + eff.grants_thorns
                defensive_buff_cards.append((i, card, val))
            if (
                eff.grants_block_next_turn
                or eff.grants_draw_next_turn
                or eff.grants_energy_next_turn
                or eff.grants_retain_hand
                or eff.grants_strength
                or eff.grants_dexterity
                or eff.grants_vigor
            ):
                val = (
                    eff.grants_block_next_turn
                    + eff.grants_draw_next_turn
                    + eff.grants_energy_next_turn
                    + (1 if eff.grants_retain_hand else 0)
                    + eff.grants_strength
                    + eff.grants_dexterity
                    + eff.grants_vigor
                )
                setup_cards.append((i, card, val))

    def _eff_sort(t: tuple) -> float:
        return t[2] / max(t[1].energy_cost, MIN_ENERGY_FOR_SORT)

    block_cards.sort(key=_eff_sort, reverse=True)
    attack_cards.sort(key=_eff_sort, reverse=True)
    draw_cards.sort(key=lambda t: t[2], reverse=True)
    poison_cards.sort(key=lambda t: t[2], reverse=True)
    aoe_cards.sort(key=_eff_sort, reverse=True)
    defensive_buff_cards.sort(key=_eff_sort, reverse=True)
    setup_cards.sort(key=_eff_sort, reverse=True)
    discard_cards.sort(key=lambda t: (t[2], -t[1].energy_cost), reverse=True)

    potential_single = sum(d for _, _, d in attack_cards) + sum(est for _, _, est in add_attack_cards)
    potential_aoe = sum(d * num_enemies for _, _, d in aoe_cards)
    potential_poison = sum(p * num_enemies for _, _, p in poison_cards)
    per_enemy_dmg = (potential_single + potential_aoe // max(num_enemies, 1) + potential_poison // max(num_enemies, 1))
    prioritize_kill = num_enemies > 0 and any(
        (e.hp + e.block) <= per_enemy_dmg for e in state.enemies
    )

    suggested: list[CardSuggestion] = []
    used_indices: set[int] = set()
    total_block_gain = 0
    total_single_dmg = 0
    total_aoe_dmg = 0
    total_poison = 0
    energy_left = energy

    weak_applied = False
    vuln_applied = False
    # Heuristic counter: how many attacks we've already planned to play this turn
    attacks_played = 0

    # "Next Skill/Attack/Power costs 0" and "Skills cost 0" – updated as we simulate playing cards
    cost_buffs: dict[str, bool] = {
        "next_skill_0": False,
        "next_attack_0": False,
        "next_power_0": False,
        "next_ethereal_0": False,
        "all_skills_0": False,
    }

    def _play_card(idx: int, card: Card, role: str, value: int, effective_cost: int):
        nonlocal energy_left, total_block_gain, total_single_dmg, total_aoe_dmg, total_poison
        if effective_cost > energy_left:
            return False
        suggested.append(CardSuggestion(
            name=card.name, role=role, value=value, energy_cost=effective_cost,
        ))
        used_indices.add(idx)
        energy_left -= effective_cost
        eff = parse_card_effects(card.name, card.card_type, card.description)
        if eff.gains_energy > 0:
            energy_left += eff.gains_energy
        # Consume "next X" buff when we use it
        if effective_cost == 0:
            if card.card_type == "skill":
                cost_buffs["next_skill_0"] = False
            if card.is_attack:
                cost_buffs["next_attack_0"] = False
            if card.card_type == "power":
                cost_buffs["next_power_0"] = False
            if eff.ethereal or "ethereal" in (card.description or "").lower():
                cost_buffs["next_ethereal_0"] = False
        # Apply cost reductions from the card we just played
        if eff.next_skill_cost_zero:
            cost_buffs["next_skill_0"] = True
        if eff.next_attack_cost_zero:
            cost_buffs["next_attack_0"] = True
        if eff.next_power_cost_zero:
            cost_buffs["next_power_0"] = True
        if eff.next_ethereal_cost_zero:
            cost_buffs["next_ethereal_0"] = True
        if eff.all_skills_cost_zero:
            cost_buffs["all_skills_0"] = True
        return True

    for idx, card, draw_val in draw_cards:
        if idx in used_indices:
            continue
        eff_cost = _effective_energy_cost(card, cost_buffs)
        if eff_cost <= energy_left:
            _play_card(idx, card, "draw", draw_val, eff_cost)

    for idx, card, est in add_attack_cards:
        if idx in used_indices:
            continue
        eff_cost = _effective_energy_cost(card, cost_buffs)
        if eff_cost <= energy_left:
            _play_card(idx, card, "add_attack", est, eff_cost)

    if hand_has_sly:
        for idx, card, discard_val in discard_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left:
                _play_card(idx, card, "discard_sly", discard_val, eff_cost)

    for idx, card, debuff_type, _ in debuff_cards:
        if idx in used_indices:
            continue
        eff_cost = _effective_energy_cost(card, cost_buffs)
        if eff_cost <= energy_left:
            if debuff_type == "vulnerable":
                vuln_applied = True
            elif debuff_type == "weak":
                weak_applied = True
            _play_card(idx, card, "debuff", 1, eff_cost)

    if vuln_applied:
        any_vuln = True
    if weak_applied and block_needed > 0:
        block_needed = max(0, int(block_needed * WEAK_BLOCK_REDUCTION))

    remaining_deficit = block_needed

    if prioritize_kill:
        for idx, card, poison_val in poison_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left and _play_card(idx, card, "poison", poison_val, eff_cost):
                total_poison += poison_val * num_enemies

        for idx, card, aoe_val in aoe_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left and _play_card(idx, card, "aoe", aoe_val * num_enemies, eff_cost):
                eff = parse_card_effects(card.name, card.card_type, card.description)
                extra = 0
                if eff.bonus_per_attack_this_turn > 0:
                    extra = eff.bonus_per_attack_this_turn * attacks_played
                total_aoe_dmg += (aoe_val + extra) * num_enemies
                attacks_played += 1
                if eff.applies_poison > 0:
                    total_poison += eff.applies_poison * num_enemies

        for idx, card, dmg in attack_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left and _play_card(idx, card, "attack", dmg, eff_cost):
                eff = parse_card_effects(card.name, card.card_type, card.description)
                extra = 0
                if eff.bonus_per_attack_this_turn > 0:
                    extra = eff.bonus_per_attack_this_turn * attacks_played
                total_single_dmg += dmg + extra
                attacks_played += 1
                if eff.applies_poison > 0:
                    total_poison += eff.applies_poison * num_enemies

        if block_needed > 0:
            for idx, card, blk in block_cards:
                if idx in used_indices:
                    continue
                eff_cost = _effective_energy_cost(card, cost_buffs)
                if eff_cost > energy_left:
                    continue
                if _play_card(idx, card, "block", blk, eff_cost):
                    total_block_gain += blk
                    remaining_deficit -= blk
                    if remaining_deficit <= 0:
                        break

            for idx, card, val in defensive_buff_cards:
                if idx in used_indices:
                    continue
                eff_cost = _effective_energy_cost(card, cost_buffs)
                if remaining_deficit > 0 and eff_cost <= energy_left:
                    _play_card(idx, card, "defensive_buff", val, eff_cost)
    else:
        if block_needed > 0:
            for idx, card, blk in block_cards:
                if idx in used_indices:
                    continue
                eff_cost = _effective_energy_cost(card, cost_buffs)
                if eff_cost > energy_left:
                    continue
                if _play_card(idx, card, "block", blk, eff_cost):
                    total_block_gain += blk
                    remaining_deficit -= blk
                    if remaining_deficit <= 0:
                        break

            for idx, card, val in defensive_buff_cards:
                if idx in used_indices:
                    continue
                eff_cost = _effective_energy_cost(card, cost_buffs)
                if eff_cost <= energy_left:
                    _play_card(idx, card, "defensive_buff", val, eff_cost)

        for idx, card, poison_val in poison_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left and _play_card(idx, card, "poison", poison_val, eff_cost):
                total_poison += poison_val * num_enemies

        for idx, card, aoe_val in aoe_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left and _play_card(idx, card, "aoe", aoe_val * num_enemies, eff_cost):
                eff = parse_card_effects(card.name, card.card_type, card.description)
                extra = 0
                if eff.bonus_per_attack_this_turn > 0:
                    extra = eff.bonus_per_attack_this_turn * attacks_played
                total_aoe_dmg += (aoe_val + extra) * num_enemies
                attacks_played += 1
                if eff.applies_poison > 0:
                    total_poison += eff.applies_poison * num_enemies

        for idx, card, dmg in attack_cards:
            if idx in used_indices:
                continue
            eff_cost = _effective_energy_cost(card, cost_buffs)
            if eff_cost <= energy_left and _play_card(idx, card, "attack", dmg, eff_cost):
                eff = parse_card_effects(card.name, card.card_type, card.description)
                extra = 0
                if eff.bonus_per_attack_this_turn > 0:
                    extra = eff.bonus_per_attack_this_turn * attacks_played
                total_single_dmg += dmg + extra
                attacks_played += 1
                if eff.applies_poison > 0:
                    total_poison += eff.applies_poison * num_enemies

    for idx, card, val in setup_cards:
        if idx in used_indices:
            continue
        eff_cost = _effective_energy_cost(card, cost_buffs)
        if eff_cost <= energy_left:
            _play_card(idx, card, "setup", val, eff_cost)

    total_dmg = total_single_dmg + total_aoe_dmg
    total_effective_block = state.player.block + total_block_gain + state.player.plating
    block_surplus = total_effective_block - incoming.total_incoming
    is_safe = block_surplus >= 0

    total_aoe_per_enemy = total_aoe_dmg // num_enemies if num_enemies else 0
    poison_per_enemy = total_poison // num_enemies if num_enemies else 0

    any_lethal: list[str] = []
    for enemy in state.enemies:
        effective_hp = enemy.hp + enemy.block
        aoe_to_them = total_aoe_per_enemy
        poison_to_them = poison_per_enemy + enemy.poison
        single_needed = max(0, effective_hp - aoe_to_them - poison_to_them)
        if single_needed <= total_single_dmg or effective_hp <= aoe_to_them + poison_to_them:
            any_lethal.append(enemy.name)

    return StrategySuggestion(
        incoming_damage=incoming.total_incoming,
        current_block=state.player.block,
        block_needed=block_needed,
        suggested_cards=suggested,
        total_block_gain=total_block_gain,
        total_damage=total_dmg,
        energy_used=energy - energy_left,
        energy_remaining=energy_left,
        block_surplus=block_surplus,
        damage_surplus=0,
        is_safe=is_safe,
        any_lethal=any_lethal,
        prioritize_kill=prioritize_kill,
    )
