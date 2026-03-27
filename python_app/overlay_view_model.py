"""
JSON view model for the Tauri/React overlay. Mirrors CombatOverlay render logic without Tkinter.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .combat_engine import (
    HandSummary,
    calculate_incoming_damage,
    summarize_hand,
)
from .models import GameState, MerchantRelic, Relic
from .overlay_settings import OverlaySettings
from .relic_db import get_short_description_only, rarity_color, rarity_sort_key
from .reward_advisor import CardRecommendation, RewardRecommendation, recommend
from .strategy import compute_strategy
from .utils import strip_bbcode

VIEW_MODEL_VERSION = 1
WARN_HP_THRESHOLD = 0.3


def should_show_card_reward(
    settings: OverlaySettings,
    state: GameState | None,
    reward_data: dict | None,
) -> bool:
    if not settings.show_card_reward:
        return False
    if not reward_data or not reward_data.get("options"):
        return False
    screen_type = reward_data.get("type", "card_reward")
    if screen_type == "merchant_cards":
        return True
    if state and state.enemies:
        return False
    return True


def _settings_public(s: OverlaySettings) -> dict[str, Any]:
    return {
        "show_combat_summary": s.show_combat_summary,
        "show_enemies": s.show_enemies,
        "show_strategy": s.show_strategy,
        "show_relics": s.show_relics,
        "show_merchant_relics": s.show_merchant_relics,
        "show_card_reward": s.show_card_reward,
        "alpha": round(max(0.35, min(1.0, s.alpha)), 4),
        "click_through": s.click_through,
    }


def _serialize_card_rec(r: CardRecommendation, is_best: bool) -> dict[str, Any]:
    return {
        "name": r.name,
        "score": r.score,
        "tier": r.tier,
        "reason": (r.reason or "").strip(),
        "mobalytics_tier": r.mobalytics_tier,
        "wiki_tier": r.wiki_tier,
        "is_best": is_best,
    }


def _reward_payload(
    data: dict,
    last_sig: str | None,
    cached: RewardRecommendation | None,
) -> tuple[dict[str, Any] | None, str | None, RewardRecommendation | None, bool, float]:
    if not data or not data.get("options"):
        return None, None, None, False, 0.0
    screen_type = data.get("type", "card_reward")
    banner = (
        "MERCHANT — CARDS FOR SALE"
        if screen_type == "merchant_cards"
        else "CHOOSE A CARD"
    )
    reward_sig = json.dumps(
        {
            "character": data.get("character", "Unknown"),
            "deck": data.get("deck", []),
            "relics": data.get("relics", []),
            "options": data.get("options", []),
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    rec: RewardRecommendation
    new_sig: str | None
    new_cache: RewardRecommendation | None
    did_compute = False
    compute_ms = 0.0
    if reward_sig == last_sig and cached is not None:
        rec = cached
        new_sig = last_sig
        new_cache = cached
    else:
        t0 = time.perf_counter()
        rec = recommend(
            character=data.get("character", "Unknown"),
            deck=data.get("deck", []),
            relics=data.get("relics", []),
            options=data.get("options", []),
        )
        compute_ms = (time.perf_counter() - t0) * 1000.0
        did_compute = True
        new_sig = reward_sig
        new_cache = rec

    best = rec.best_card
    rows = [_serialize_card_rec(r, r.name == best) for r in rec.recommendations]
    out: dict[str, Any] = {
        "banner": banner,
        "wiki_build_title": rec.wiki_build_title,
        "recommendations": rows,
        "warnings": list(rec.warnings),
    }
    return out, new_sig, new_cache, did_compute, compute_ms


def build_overlay_view_model(
    settings: OverlaySettings,
    state: GameState | None,
    reward_data: dict | None,
    *,
    debug: bool,
    reward_file_path: str,
    reward_cache_sig: str | None,
    reward_cache_rec: RewardRecommendation | None,
    perf_render_count: int,
    perf_render_ms_total: float,
    perf_reward_rec_count: int,
    perf_reward_rec_ms_total: float,
) -> tuple[dict[str, Any], str | None, RewardRecommendation | None, int, float]:
    """Return payload, reward cache key/val, and reward perf deltas (count, ms) for this build."""
    show_pick = should_show_card_reward(settings, state, reward_data)
    s = settings
    card_advisor = None
    new_sig = reward_cache_sig
    new_rec = reward_cache_rec
    reward_delta_count = 0
    reward_delta_ms = 0.0
    if show_pick and s.show_card_reward and reward_data:
        card_advisor, new_sig, new_rec, did_r, rms = _reward_payload(
            reward_data, reward_cache_sig, reward_cache_rec
        )
        if did_r:
            reward_delta_count = 1
            reward_delta_ms = rms

    incoming = None
    if state and state.enemies and (s.show_combat_summary or s.show_enemies):
        incoming = calculate_incoming_damage(state)

    combat_summary = None
    if state and s.show_combat_summary:
        combat_summary = _combat_summary_block(state, incoming)

    enemies = None
    if state and not show_pick and s.show_enemies and state.enemies:
        enemies = _enemies_block(state, incoming)

    strategy = None
    if state and not show_pick and s.show_strategy and state.hand and state.enemies:
        strategy = _strategy_block(state)

    relics = None
    if state and s.show_relics and state.relics:
        relics = _relics_block(state.relics)

    at_merchant_cards = show_pick and (reward_data or {}).get("type") == "merchant_cards"
    merchant_relics = None
    if (
        state
        and state.merchant_relics
        and s.show_merchant_relics
        and (not show_pick or at_merchant_cards)
    ):
        merchant_relics = _merchant_relics_block(state.merchant_relics)

    status_text = _status_text(state, show_pick, reward_data, s)
    debug_block = None
    if debug:
        debug_block = _debug_block(
            reward_file_path,
            reward_data,
            perf_render_count,
            perf_render_ms_total,
            perf_reward_rec_count + reward_delta_count,
            perf_reward_rec_ms_total + reward_delta_ms,
        )

    payload: dict[str, Any] = {
        "v": VIEW_MODEL_VERSION,
        "meta": {
            "status_text": status_text,
            "turn": state.turn if state else None,
            "settings": _settings_public(s),
            "debug": debug,
        },
        "combat_summary": combat_summary,
        "enemies": enemies,
        "strategy": strategy,
        "relics": relics,
        "merchant_relics": merchant_relics,
        "card_advisor": card_advisor,
        "debug": debug_block,
    }
    return payload, new_sig, new_rec, reward_delta_count, reward_delta_ms


def _status_text(
    state: GameState | None,
    show_pick: bool,
    reward_data: dict | None,
    s: OverlaySettings,
) -> str:
    if show_pick:
        if (reward_data or {}).get("type") == "merchant_cards":
            return "Merchant cards  |  Card advisor"
        return "Choose a Card  |  Card advisor"
    if state:
        if not any(
            (
                s.show_combat_summary,
                s.show_enemies,
                s.show_strategy,
                s.show_relics,
                s.show_merchant_relics,
            )
        ):
            return "All panels off — open ⚙ settings"
        return f"Turn {state.turn}  |  Updated"
    return "Waiting for game state...  (⚙ = settings)"


def _combat_summary_block(
    state: GameState,
    incoming: Any | None,
) -> dict[str, Any]:
    p = state.player
    if incoming is None and state.enemies:
        incoming = calculate_incoming_damage(state)
    parts = [f"HP: {p.hp}/{p.max_hp}", f"Energy: {p.energy}/{p.max_energy}"]
    str_text = f"STR: {p.strength:+d}" if p.strength != 0 else "STR: 0"
    dex_text = f"DEX: {p.dexterity:+d}" if p.dexterity != 0 else "DEX: 0"
    parts += [str_text, dex_text]
    if p.block > 0:
        parts.append(f"⛨ {p.block}")
    stats_line = "  ".join(parts)

    net: dict[str, Any] | None = None
    if state.enemies and incoming is not None and incoming.total_incoming > 0:
        if incoming.expected_hp == 0:
            net = {
                "kind": "lethal",
                "text": f"  ☠  LETHAL!  {incoming.net_damage} dmg  →  HP: 0",
            }
        elif incoming.net_damage == 0:
            net = {
                "kind": "safe",
                "text": f"  ✔  SAFE  —  block covers all {incoming.total_incoming} dmg",
            }
        elif incoming.net_damage < p.hp * WARN_HP_THRESHOLD:
            net = {
                "kind": "warn",
                "text": f"  ▼  {incoming.net_damage} dmg incoming  →  HP: {incoming.expected_hp}",
            }
        else:
            net = {
                "kind": "danger",
                "text": f"  ▼  {incoming.net_damage} dmg incoming  →  HP: {incoming.expected_hp}",
            }
    elif state.enemies and incoming is not None:
        net = {"kind": "safe", "text": "  ✔  No attack incoming this turn"}

    return {"stats_line": stats_line, "net": net}


def _enemies_block(state: GameState, incoming: Any | None) -> dict[str, Any]:
    if incoming is None:
        incoming = calculate_incoming_damage(state)
    rows: list[dict[str, Any]] = []
    for ei, enemy in zip(incoming.per_enemy, state.enemies):
        badges: list[str] = []
        if enemy.weak_turns > 0:
            badges.append("Weak")
        if enemy.vulnerable_turns > 0:
            badges.append("Vuln")
        if enemy.strength != 0:
            badges.append(f"STR{enemy.strength:+d}")
        if ei.total_damage > 0:
            if ei.intended_hits > 1:
                per_hit = ei.intended_damage // max(ei.intended_hits, 1)
                dmg_str = f"{per_hit}x{ei.intended_hits} ({ei.total_damage})"
            else:
                dmg_str = str(ei.total_damage)
            intent_kind = "attack"
            intent_text = f"⚔ {dmg_str} dmg"
        else:
            intent_kind = "other"
            intent_text = f"• {ei.move_type.replace('Intent', '')}"
        rows.append(
            {
                "name": ei.name,
                "intent_kind": intent_kind,
                "intent_text": intent_text,
                "hp_text": f"HP {enemy.hp}/{enemy.max_hp}",
                "badges": badges,
            }
        )
    block_line = None
    if incoming.player_block > 0:
        absorbed = min(incoming.player_block, incoming.total_incoming)
        block_line = (
            f"  ⛨ Your block: {incoming.player_block}  —  absorbs {absorbed} of {incoming.total_incoming} dmg"
        )
    return {"title": f"ENEMIES ({len(state.enemies)})", "rows": rows, "block_line": block_line}


def _hand_summary_lines(hs: HandSummary) -> list[str]:
    lines = [
        f"  ⚔ ATK: {hs.attack_count}  |  max {hs.max_playable_damage} dmg  "
        f"(pot. {hs.total_potential_damage}, {hs.total_attack_energy}E)",
        f"  ⛨ BLK: {hs.block_count}  |  max {hs.max_playable_block} blk  "
        f"(pot. {hs.total_potential_block}, {hs.total_block_energy}E)",
    ]
    if hs.other_count > 0:
        lines.append(f"  ✦ Other: {hs.other_count} cards")
    return lines


def _strategy_block(state: GameState) -> dict[str, Any]:
    strat = compute_strategy(state)
    hs = summarize_hand(state)
    if strat.is_safe:
        safety = {"kind": "safe", "text": f"  ✔ SAFE  (block surplus: +{strat.block_surplus})"}
    elif strat.prioritize_kill and strat.any_lethal:
        safety = {
            "kind": "lethal",
            "text": "  ⚔ KILL POSSIBLE  — attack first, then block if needed",
        }
    elif strat.block_needed > 0 and strat.total_block_gain < strat.block_needed:
        deficit = strat.block_needed - strat.total_block_gain
        safety = {"kind": "danger", "text": f"  ⚠ DANGER  (need {deficit} more block!)"}
    else:
        net = strat.incoming_damage - strat.current_block - strat.total_block_gain
        safety = {"kind": "warn", "text": f"  ⚠ TAKING {max(net, 0)} dmg"}

    suggested: list[dict[str, Any]] = []
    for cs in strat.suggested_cards:
        if cs.role == "block":
            role = "block"
            val = f"+{cs.value} blk"
        elif cs.role == "add_attack":
            role = "add_attack"
            val = "random atk (play first)"
        else:
            role = "attack"
            val = f"{cs.value} dmg"
        suggested.append(
            {
                "name": cs.name,
                "role": role,
                "value_text": val,
                "energy_cost": cs.energy_cost,
            }
        )
    kills = list(strat.any_lethal) if strat.any_lethal else []
    summary = (
        f"  Total: {strat.total_damage} dmg + {strat.total_block_gain} blk  "
        f"| {strat.energy_used}E used, {strat.energy_remaining}E left"
    )
    return {
        "hand_lines": _hand_summary_lines(hs),
        "safety": safety,
        "lethal_targets": kills,
        "suggested": suggested,
        "summary_line": summary,
    }


def _relics_block(relics: list[Relic]) -> dict[str, Any]:
    sorted_relics = sorted(relics, key=lambda r: rarity_sort_key(r.rarity))
    with_short: list[dict[str, str]] = []
    without_names: list[str] = []
    for relic in sorted_relics:
        short = strip_bbcode(get_short_description_only(relic.name))
        if short:
            with_short.append(
                {"name": relic.name, "short": short, "color": rarity_color(relic.rarity)}
            )
        else:
            without_names.append(relic.name)
    return {
        "title": f"RELICS ({len(sorted_relics)})",
        "with_short": with_short,
        "other_names": without_names,
    }


def _merchant_relics_block(merchant_relics: list[MerchantRelic]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for mr in sorted(merchant_relics, key=lambda r: rarity_sort_key(r.rarity)):
        short = strip_bbcode(get_short_description_only(mr.name))
        rows.append(
            {
                "name": mr.name,
                "rarity": mr.rarity.upper(),
                "cost": mr.cost,
                "short": short or "",
                "color": rarity_color(mr.rarity),
            }
        )
    return {"title": f"🛒  MERCHANT RELICS ({len(merchant_relics)})", "rows": rows}


def _debug_block(
    reward_file_path: str,
    reward_data: dict | None,
    perf_render_count: int,
    perf_render_ms_total: float,
    perf_reward_rec_count: int,
    perf_reward_rec_ms_total: float,
) -> dict[str, Any]:
    p = Path(reward_file_path) if reward_file_path else None
    exists = bool(p and p.exists())
    mtime = ""
    size = ""
    if exists and p:
        try:
            stat = p.stat()
            mtime = time.strftime("%H:%M:%S", time.localtime(stat.st_mtime))
            size = f"{stat.st_size}B"
        except OSError:
            pass
    rd = reward_data or {}
    opts = rd.get("options") or []
    opts_preview = ", ".join(str(x) for x in opts[:3])
    if len(opts) > 3:
        opts_preview += f", …(+{len(opts)-3})"
    deck = rd.get("deck") or []
    deck_uniq = len({str(c).lower() for c in deck})
    deck_preview = ", ".join(str(x) for x in deck[:6])
    if len(deck) > 6:
        deck_preview += f", …(+{len(deck)-6})"

    def _avg(total: float, count: int) -> float:
        return (total / count) if count > 0 else 0.0

    lines = [
        f"Reward file: {reward_file_path or '(not set)'}",
        f"Exists: {exists}  MTime: {mtime or '-'}  Size: {size or '-'}",
        f"Parsed options: {len(opts)}  [{opts_preview}]",
        f"Reward deck: {len(deck)} cards, {deck_uniq} unique  [{deck_preview}]",
        f"Reward character: {rd.get('character', '-')!r}  type: {rd.get('type', '-')!r}",
        f"Perf renders: {perf_render_count} avg_ms={_avg(perf_render_ms_total, perf_render_count):.2f}",
        f"Perf reward recommend: {perf_reward_rec_count} avg_ms={_avg(perf_reward_rec_ms_total, perf_reward_rec_count):.2f}",
    ]
    return {"lines": lines}
