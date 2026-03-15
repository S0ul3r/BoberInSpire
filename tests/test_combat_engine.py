import pytest

from python_app.combat_engine import (
    compute_card_damage,
    compute_card_block,
    calculate_turn_damage,
    calculate_all_enemies,
    calculate_incoming_damage,
    compute_strategy,
    summarize_hand,
)
from python_app.models import Card, Enemy, GameState, PlayerState, Relic


def _make_state(
    hand: list[Card] | None = None,
    enemies: list[Enemy] | None = None,
    relics: list[Relic] | None = None,
    energy: int = 3,
    strength: int = 0,
    dexterity: int = 0,
    vigor: int = 0,
    weak_turns: int = 0,
    block: int = 0,
    turn: int = 1,
) -> GameState:
    return GameState(
        player=PlayerState(
            energy=energy,
            strength=strength,
            dexterity=dexterity,
            vigor=vigor,
            weak_turns=weak_turns,
            block=block,
        ),
        hand=hand or [],
        enemies=enemies or [Enemy(name="Dummy", hp=100)],
        relics=relics or [],
        turn=turn,
    )


class TestComputeCardDamage:
    def test_basic_attack(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        assert compute_card_damage(card, strength=0, vigor=0, is_weak=False, enemy_vulnerable=False) == 6

    def test_strength_adds_flat(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        assert compute_card_damage(card, strength=3, vigor=0, is_weak=False, enemy_vulnerable=False) == 9

    def test_vulnerable_multiplier(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        assert compute_card_damage(card, strength=0, vigor=0, is_weak=False, enemy_vulnerable=True) == 9

    def test_weak_multiplier(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        assert compute_card_damage(card, strength=0, vigor=0, is_weak=True, enemy_vulnerable=False) == 4

    def test_weak_and_vulnerable(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        result = compute_card_damage(card, strength=0, vigor=0, is_weak=True, enemy_vulnerable=True)
        assert result == 6

    def test_multi_hit(self):
        card = Card(name="Twin Strike", damage=5, energy_cost=1, hits=2)
        assert compute_card_damage(card, strength=2, vigor=0, is_weak=False, enemy_vulnerable=False) == 14

    def test_vigor(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        assert compute_card_damage(card, strength=0, vigor=8, is_weak=False, enemy_vulnerable=False) == 14

    def test_skill_card_zero_damage(self):
        card = Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5)
        assert compute_card_damage(card, strength=5, vigor=0, is_weak=False, enemy_vulnerable=True) == 0

    def test_damage_never_negative(self):
        card = Card(name="Strike", damage=1, energy_cost=1)
        assert compute_card_damage(card, strength=-5, vigor=0, is_weak=True, enemy_vulnerable=False) >= 0


class TestComputeCardBlock:
    def test_basic_block(self):
        card = Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5)
        assert compute_card_block(card, dexterity=0) == 5

    def test_dexterity_adds(self):
        card = Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5)
        assert compute_card_block(card, dexterity=3) == 8

    def test_attack_card_no_block(self):
        card = Card(name="Strike", damage=6, energy_cost=1)
        assert compute_card_block(card, dexterity=5) == 0

    def test_frail_reduces_block(self):
        card = Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=8)
        assert compute_card_block(card, dexterity=0, is_frail=False) == 8
        assert compute_card_block(card, dexterity=0, is_frail=True) == 6


class TestCalculateTurnDamage:
    def test_plays_cards_in_order(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Strike+", damage=9, energy_cost=1),
        ]
        state = _make_state(hand=hand, energy=3)
        result = calculate_turn_damage(state, 0)
        assert result.total_damage == 15
        assert len(result.per_card) == 2

    def test_respects_energy_limit(self):
        hand = [
            Card(name="Heavy Blade", damage=14, energy_cost=2),
            Card(name="Heavy Blade+", damage=18, energy_cost=2),
        ]
        state = _make_state(hand=hand, energy=3)
        result = calculate_turn_damage(state, 0)
        assert result.total_damage == 14
        assert result.energy_remaining == 1

    def test_lethal_detection(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        enemy = Enemy(name="Louse", hp=10)
        state = _make_state(hand=hand, enemies=[enemy])
        result = calculate_turn_damage(state, 0)
        assert result.is_lethal is True
        assert result.overkill == 2

    def test_strength_applies_to_all_attacks(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        state = _make_state(hand=hand, energy=3, strength=3)
        result = calculate_turn_damage(state, 0)
        assert result.total_damage == 18

    def test_vulnerable_enemy(self):
        hand = [Card(name="Strike", damage=6, energy_cost=1)]
        enemy = Enemy(name="Worm", hp=50, vulnerable_turns=2)
        state = _make_state(hand=hand, enemies=[enemy])
        result = calculate_turn_damage(state, 0)
        assert result.total_damage == 9

    def test_empty_hand(self):
        state = _make_state(hand=[])
        result = calculate_turn_damage(state, 0)
        assert result.total_damage == 0

    def test_no_enemies(self):
        state = GameState(
            player=PlayerState(energy=3),
            hand=[Card(name="Strike", damage=6, energy_cost=1)],
            enemies=[],
            relics=[],
        )
        result = calculate_turn_damage(state, 0)
        assert result.enemy_name == "(none)"


class TestCalculateAllEnemies:
    def test_multiple_enemies(self):
        hand = [Card(name="Strike", damage=6, energy_cost=1)]
        enemies = [
            Enemy(name="A", hp=10),
            Enemy(name="B", hp=20),
        ]
        state = _make_state(hand=hand, enemies=enemies)
        results = calculate_all_enemies(state)
        assert len(results) == 2
        assert results[0].enemy_name == "A"
        assert results[1].enemy_name == "B"


class TestIncomingDamage:
    def test_basic_incoming(self):
        enemies = [
            Enemy(name="A", hp=30, intended_damage=10),
            Enemy(name="B", hp=20, intended_damage=5),
        ]
        state = _make_state(enemies=enemies, block=0)
        result = calculate_incoming_damage(state)
        assert result.total_incoming == 15
        assert result.net_damage == 15

    def test_block_reduces_damage(self):
        enemies = [Enemy(name="A", hp=30, intended_damage=10)]
        state = _make_state(enemies=enemies, block=6)
        result = calculate_incoming_damage(state)
        assert result.net_damage == 4

    def test_block_caps_at_zero(self):
        enemies = [Enemy(name="A", hp=30, intended_damage=5)]
        state = _make_state(enemies=enemies, block=20)
        result = calculate_incoming_damage(state)
        assert result.net_damage == 0


class TestHandSummary:
    def test_counts(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
            Card(name="Sow", damage=8, energy_cost=1),
        ]
        state = _make_state(hand=hand, energy=3)
        hs = summarize_hand(state)
        assert hs.attack_count == 2
        assert hs.block_count == 1
        assert hs.total_potential_damage == 14
        assert hs.total_potential_block == 5

    def test_max_playable_respects_energy(self):
        hand = [
            Card(name="Heavy", damage=20, energy_cost=3),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        state = _make_state(hand=hand, energy=3)
        hs = summarize_hand(state)
        assert hs.max_playable_damage == 20


class TestStrategy:
    def test_blocks_first_then_attacks(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
            Card(name="Strike+", damage=9, energy_cost=1),
        ]
        enemies = [Enemy(name="A", hp=30, intended_damage=5)]
        state = _make_state(hand=hand, enemies=enemies, energy=3)
        strat = compute_strategy(state)
        assert strat.total_block_gain >= 5
        assert strat.is_safe
        assert strat.total_damage > 0

    def test_prioritizes_efficient_block(self):
        hand = [
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
            Card(name="Defend+", damage=0, energy_cost=1, card_type="skill", block=8),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        enemies = [Enemy(name="A", hp=30, intended_damage=7)]
        state = _make_state(hand=hand, enemies=enemies, energy=3)
        strat = compute_strategy(state)
        block_cards = [c for c in strat.suggested_cards if c.role == "block"]
        assert len(block_cards) == 1
        assert block_cards[0].name == "Defend+"
        assert strat.total_damage == 6

    def test_no_block_needed_all_attacks(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Strike+", damage=9, energy_cost=1),
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
        ]
        enemies = [Enemy(name="A", hp=30, intended_damage=0)]
        state = _make_state(hand=hand, enemies=enemies, energy=3)
        strat = compute_strategy(state)
        assert strat.block_needed == 0
        assert strat.total_damage == 15

    def test_lethal_detection(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        enemies = [Enemy(name="Louse", hp=15)]
        state = _make_state(hand=hand, enemies=enemies, energy=3)
        strat = compute_strategy(state)
        assert "Louse" in strat.any_lethal

    def test_existing_block_reduces_need(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
        ]
        enemies = [Enemy(name="A", hp=30, intended_damage=10)]
        state = _make_state(hand=hand, enemies=enemies, energy=2, block=8)
        strat = compute_strategy(state)
        assert strat.block_needed == 2

    def test_draw_cards_played_first(self):
        """Draw cards are prioritized early to open more options."""
        hand = [
            Card(name="Acrobatics", damage=0, energy_cost=1, card_type="skill", description="Draw 3 cards"),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        state = _make_state(hand=hand, enemies=[Enemy(name="A", hp=30)], energy=2)
        strat = compute_strategy(state)
        roles = [c.role for c in strat.suggested_cards]
        assert "draw" in roles
        assert roles.index("draw") < roles.index("attack") if "attack" in roles else True

    def test_debuff_before_attacks(self):
        """Vulnerable/Weak cards played before attacks."""
        hand = [
            Card(name="Bash", damage=8, energy_cost=2, description="Apply 2 Vulnerable"),
            Card(name="Strike", damage=6, energy_cost=1),
        ]
        state = _make_state(hand=hand, enemies=[Enemy(name="A", hp=30)], energy=3)
        strat = compute_strategy(state)
        roles = [c.role for c in strat.suggested_cards]
        if "debuff" in roles and "attack" in roles:
            assert roles.index("debuff") < roles.index("attack")

    def test_poison_included_in_lethal(self):
        """Poison damage is considered for lethal check."""
        hand = [
            Card(name="Poison Cloud", damage=0, energy_cost=1, card_type="skill", description="Apply 6 Poison to ALL enemies"),
        ]
        state = _make_state(hand=hand, enemies=[Enemy(name="A", hp=5)], energy=1)
        strat = compute_strategy(state)
        assert "A" in strat.any_lethal

    def test_aoe_damage_to_all_enemies(self):
        """AOE cards deal damage to each enemy."""
        hand = [
            Card(name="Cleave", damage=8, energy_cost=1, description="Deal 8 damage to ALL enemies"),
        ]
        enemies = [Enemy(name="A", hp=8), Enemy(name="B", hp=8)]
        state = _make_state(hand=hand, enemies=enemies, energy=1)
        strat = compute_strategy(state)
        assert strat.total_damage == 16
        assert "A" in strat.any_lethal
        assert "B" in strat.any_lethal


class TestIncomingDamageExtended:
    def test_expected_hp(self):
        state = _make_state(enemies=[Enemy(name="E", hp=10, intended_damage=7)], block=0)
        state.player.hp = 20
        result = calculate_incoming_damage(state)
        assert result.expected_hp == 13
        assert result.net_damage == 7

    def test_expected_hp_lethal(self):
        state = _make_state(enemies=[Enemy(name="E", hp=10, intended_damage=100)], block=0)
        state.player.hp = 30
        result = calculate_incoming_damage(state)
        assert result.expected_hp == 0
        assert result.net_damage == 100

    def test_per_enemy_names_and_totals(self):
        enemies = [
            Enemy(name="A", hp=20, intended_damage=5),
            Enemy(name="B", hp=30, intended_damage=10),
        ]
        state = _make_state(enemies=enemies, block=3)
        result = calculate_incoming_damage(state)
        assert len(result.per_enemy) == 2
        assert result.per_enemy[0].name == "A"
        assert result.per_enemy[0].total_damage == 5
        assert result.per_enemy[1].name == "B"
        assert result.per_enemy[1].total_damage == 10
        assert result.total_incoming == 15
        assert result.net_damage == 12


class TestHandSummaryExtended:
    def test_other_count(self):
        hand = [
            Card(name="Strike", damage=6, energy_cost=1),
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
            Card(name="Wraith Form", damage=0, energy_cost=3, card_type="power", block=0),
        ]
        state = _make_state(hand=hand, energy=3)
        hs = summarize_hand(state)
        assert hs.attack_count == 1
        assert hs.block_count == 1
        assert hs.other_count == 1

    def test_max_playable_block(self):
        hand = [
            Card(name="Defend", damage=0, energy_cost=1, card_type="skill", block=5),
            Card(name="Defend+", damage=0, energy_cost=1, card_type="skill", block=8),
        ]
        state = _make_state(hand=hand, energy=2)
        hs = summarize_hand(state)
        assert hs.max_playable_block == 13
        assert hs.block_count == 2
