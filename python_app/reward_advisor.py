"""
Card reward advisor: scores offered cards based on deck, archetype, and build guides.
Uses game-exported deck/relics and reward options to recommend the best pick.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from .card_db import lookup_card

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MOBALYTICS_TIERS_PATH = DATA_DIR / "tier_lists" / "mobalytics_cards.json"

# Numeric anchors for Mobalytics S–D (used when blending with archetype score)
MOBALYTICS_TIER_SCORE: dict[str, int] = {
    "S": 92,
    "A": 78,
    "B": 64,
    "C": 50,
    "D": 36,
}
MOBALYTICS_BLEND_WEIGHT = 0.55  # tier list vs archetype heuristic

# Card names referenced many times (archetype tables + scorers)
CARD_BODY_SLAM = "Body Slam"
CARD_TRUE_GRIT = "True Grit"
CARD_ASHEN_STRIKE = "Ashen Strike"
CARD_PACTS_END = "Pact's End"
CARD_PERFECTED_STRIKE = "Perfected Strike"
CARD_TWIN_STRIKE = "Twin Strike"
CARD_PULL_AGGRO = "Pull Aggro"
CARD_ALL_FOR_ONE = "All for One"
CARD_IRON_CLUB = "Iron Club"
CARD_ORNAMENTAL_FAN = "Ornamental Fan"
REASON_DECK_BLOAT = "Deck bloat risk"

IRONCLAD_EXHAUST_FINISHERS: tuple[str, ...] = (
    CARD_ASHEN_STRIKE,
    CARD_PACTS_END,
    CARD_BODY_SLAM,
)

# Archetype detection signals and card priorities for Ironclad (from ironclad_guide.md)
IRONCLAD_ARCHETYPES = {
    "exhaust": {
        "signals": ["Corruption"],
        "early": ["Corruption", CARD_TRUE_GRIT, CARD_BODY_SLAM],
        "mid": [CARD_ASHEN_STRIKE, "Burning Pact", "Evil Eye", "Feel No Pain", "Forgotten Ritual"],
        "high": ["Dark Embrace", "Brand", "Offering", CARD_PACTS_END, "Thrash", "Juggernaut"],
        "relics": ["Charon's Ashes", "Forgotten Soul", "Burning Sticks", "Joss Paper"],
    },
    "bloodletting": {
        "signals": ["Rupture", "Inferno"],
        "early": ["Breakthrough", "Bloodletting"],
        "mid": ["Rupture", "Inferno", "Hemokinesis"],
        "high": ["Crimson Mantle", "Brand", "Offering", "Feed", "Tear Asunder"],
        "relics": ["Centennial Puzzle", "Demon Tongue", "Self-Forming Clay"],
    },
    "strike": {
        "signals": [CARD_PERFECTED_STRIKE],
        "early": [CARD_PERFECTED_STRIKE, CARD_TWIN_STRIKE, "Pommel Strike", "Breakthrough", "Tremble"],
        "mid": ["Taunt", "Expect a Fight"],
        "high": ["Pyre", "Hellraiser", "Colossus", "Cruelty"],
        "relics": ["Strike Dummy", "Intimidating Helmet"],
    },
    "block": {
        "signals": ["Barricade", "Juggernaut"],
        "early": [CARD_BODY_SLAM, "Shrug It Off", CARD_TRUE_GRIT],
        "mid": ["Flame Barrier", "Taunt", "Stone Armor"],
        "high": ["Juggernaut", "Barricade", "Crimson Mantle", "Impervious"],
        "relics": ["Cloak Clasp", "Fresnel Lens", "Vambrace", "Sai", "Parrying Shield", "Pael's Legion", "Bronze Scales"],
    },
    "strength": {
        "signals": ["Demon Form", "Inflame"],
        "early": [CARD_TWIN_STRIKE],
        "mid": ["Fight Me!", "Inflame", "Rupture", "Whirlwind"],
        "high": ["Demon Form", "Brand", "Thrash"],
        "relics": ["Anchor", "Horn Cleat", "Permafrost", "Brimstone", "Ruined Helmet", "Sword of Jade"],
    },
}

# Cross-archetype cards (bonus when in multiple archetypes)
# Necrobinder archetypes
NECROBINDER_ARCHETYPES = {
    "doom": {
        "signals": ["Blight Strike", "Scourge", "Deathbringer", "No Escape"],
        "early": ["Blight Strike", "Defile", "Negative Pulse", "Scourge"],
        "mid": ["Deathbringer", "Delay"],
        "high": ["Death's Door", "End of Days", "No Escape", "Oblivion", "Shroud", "Time's Up"],
        "relics": ["Book Repair Knife", "Undying Sigil"],
    },
    "osty": {
        "signals": [CARD_PULL_AGGRO, "Snap", "Sic 'Em", "Rattle"],
        "early": [CARD_PULL_AGGRO, "Snap"],
        "mid": ["High Five", "Rattle"],
        "high": ["Fetch", "Flatten", "Necro Mastery", "Reanimate", "Sic 'Em", "Spur"],
        "relics": ["Bone Flute"],
    },
}

# Defect archetypes
DEFECT_ARCHETYPES = {
    "claw": {
        "signals": ["Claw", "Scrape", CARD_ALL_FOR_ONE],
        "early": ["Claw", "Momentum Strike", "Beam Cell", "Go for the Eyes", "Flash of Steel"],
        "mid": ["Scrape", "FTL", "Skim", "Hologram"],
        "high": [CARD_ALL_FOR_ONE, "Feral", "Machine Learning", "Panache", "Secret Weapon"],
        "relics": [CARD_IRON_CLUB, "Nunchaku", "Shuriken", "Kunai", CARD_ORNAMENTAL_FAN, "Kusarigama", "Power Cell"],
    },
    "orb": {
        "signals": ["Defragment", "Capacitor", "Loop", "Coolheaded"],
        "early": ["Ball Lightning", "Cold Snap", "Coolheaded", "Barrage", "Compile Driver", "Lightning Rod"],
        "mid": ["Glacier", "Chaos", "Capacitor", "Loop", "Thunder", "Hailstorm"],
        "high": ["Defragment", "Modded", "Multi-Cast", "Voltaic", "Tesla Coil"],
        "relics": ["Emotion Chip", "Gold-Plated Cables", "Metronome", "Runic Capacitor", "Data Disk"],
    },
}

# Regent archetypes
REGENT_ARCHETYPES = {
    "blade": {
        "signals": ["Summon Forth", "Beat into Shape"],
        "early": ["Cosmic Indifference", "Wrought in War"],
        "mid": ["Bulwark", "Summon Forth"],
        "high": ["Beat into Shape", "Conqueror", "Furnace", "Seeking Edge"],
        "relics": ["Fencing Manual"],
    },
    "star": {
        "signals": ["Shining Strike", "Hidden Cache", "Genesis"],
        "early": ["Gather Light", "Glow", "Hidden Cache", "Solar Strike"],
        "mid": ["Convergence", "Shining Strike"],
        "high": ["Alignment", "Cloak of Stars", "Dying Star", "Gamma Blast", "Genesis", "Reflect", "The Smith"],
        "relics": ["Lunar Pastry", "Mini Regent"],
    },
}

# Silent archetypes
SILENT_ARCHETYPES = {
    "shiv": {
        "signals": ["Accuracy", "Infinite Blades", "Cloak and Dagger", "Leading Strike"],
        "early": ["Leading Strike", "Cloak and Dagger", "Blade Dance"],
        "mid": ["Accuracy", "Infinite Blades", "Hidden Daggers"],
        "high": ["Fan of Knives", "Knife Trap", "Finisher", "Afterimage", "Serpent Form"],
        "relics": ["Ninja Scroll", "Helical Dart", CARD_IRON_CLUB, "Nunchaku", "Shuriken", "Kunai", CARD_ORNAMENTAL_FAN, "Kusarigama", "Joss Paper"],
    },
    "poison": {
        "signals": ["Deadly Poison", "Poisoned Stab", "Noxious Fumes"],
        "early": ["Poisoned Stab", "Deadly Poison"],
        "mid": ["Haze", "Noxious Fumes", "Outbreak"],
        "high": ["Accelerant", "Bubble Bubble", "Mirage", "Burst"],
        "relics": ["Snecko Skull", "Unsettling Lamp", "Twisted Funnel", "History Course"],
    },
    "sly": {
        "signals": ["Tactician", "Tools of the Trade"],
        "early": ["Flick-Flack", "Ricochet", "Untouchable", "Acrobatics", "Dagger Throw", "Prepared"],
        "mid": ["Haze", "Reflex", "Tactician", "Calculated Gamble", "Speedster"],
        "high": ["Tools of the Trade", "Master Planner", "Abrasive", "Serpent Form"],
        "relics": ["Tingsha", "Tough Bandages", CARD_IRON_CLUB, "Nunchaku", "Shuriken", "Kunai", CARD_ORNAMENTAL_FAN, "Kusarigama", "Pendulum", "The Abacus"],
    },
}

IRONCLAD_CROSSOVER = {
    CARD_TWIN_STRIKE: ["strength", "strike"],
    CARD_BODY_SLAM: ["block", "exhaust"],
    "Brand": ["strength", "exhaust", "bloodletting"],
    CARD_TRUE_GRIT: ["block", "exhaust"],
    "Rupture": ["strength", "bloodletting"],
    "Breakthrough": ["bloodletting", "strike"],
    "Juggernaut": ["block", "exhaust"],
    "Taunt": ["block", "strike"],
}


@dataclass
class CardRecommendation:
    name: str
    score: int
    tier: str
    reason: str


@dataclass
class RewardRecommendation:
    recommendations: list[CardRecommendation]
    best_card: str
    archetype: str
    warnings: list[str] = field(default_factory=list)


def _normalize_name(name: str) -> str:
    """Normalize card name for matching."""
    return name.strip()


def _norm_in_card_list(normalized_name: str, card_list: list[str]) -> bool:
    """True if normalized_name fuzzy-matches any entry in card_list."""
    n = normalized_name.lower()
    return any(n in c.lower() or c.lower() in n for c in card_list)


def _base_card_name(name: str) -> str:
    """Strip upgrade suffix (e.g. Monologue+ -> Monologue) for tier-list lookup."""
    s = name.strip()
    while s.endswith("+"):
        s = s[:-1].rstrip()
    return s.strip()


def _fill_tier_index(idx: dict[str, str], tier_key: str, names: object) -> None:
    """Add card names from one tier bucket into idx (lowercase -> tier letter)."""
    if len(tier_key) != 1 or tier_key not in MOBALYTICS_TIER_SCORE:
        return
    if not isinstance(names, list):
        return
    for n in names:
        if isinstance(n, str) and n.strip():
            idx[n.strip().lower()] = tier_key


@lru_cache(maxsize=1)
def _load_mobalytics_index() -> dict[str, dict[str, str]]:
    """
    character_name -> lowercase_base_card_name -> tier letter (S/A/B/C/D).
    """
    if not MOBALYTICS_TIERS_PATH.is_file():
        return {}
    try:
        raw = json.loads(MOBALYTICS_TIERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[str, str]] = {}
    chars = (raw.get("characters") or {}) if isinstance(raw, dict) else {}
    for char_name, tiers in chars.items():
        if not isinstance(tiers, dict):
            continue
        idx: dict[str, str] = {}
        for tier_key, names in tiers.items():
            _fill_tier_index(idx, tier_key, names)
        out[str(char_name)] = idx
    return out


def _mobalytics_character_key(character: str) -> str | None:
    """Map exported game character string to JSON key (Ironclad, Silent, ...)."""
    cl = character.lower().replace("_", " ").replace(".", " ")
    if "ironclad" in cl:
        return "Ironclad"
    if "silent" in cl:
        return "Silent"
    if "regent" in cl:
        return "Regent"
    if "necrobinder" in cl:
        return "Necrobinder"
    if "defect" in cl:
        return "Defect"
    return None


def mobalytics_tier_for(character: str, card_name: str) -> str | None:
    """Public helper: Mobalytics tier letter for this card, or None if unknown."""
    ck = _mobalytics_character_key(character)
    if not ck:
        return None
    idx = _load_mobalytics_index().get(ck)
    if not idx:
        return None
    base = _base_card_name(card_name).lower()
    return idx.get(base)


def _deck_contains(deck: list[str], card_name: str) -> bool:
    """Check if deck contains a card (case-insensitive, partial match)."""
    needle = card_name.lower()
    for c in deck:
        if needle in c.lower() or c.lower() in needle:
            return True
    return False


def _count_strikes(deck: list[str]) -> int:
    """Count cards with 'Strike' in the name."""
    return sum(1 for c in deck if "strike" in c.lower())


def _detect_archetype(character: str, deck: list[str], relics: list[str]) -> str:
    """Detect dominant archetype for the given character."""
    cl = character.lower()
    if "ironclad" in cl:
        return _detect_ironclad_archetype(deck, relics)
    if "necrobinder" in cl:
        return _detect_necrobinder_archetype(deck, relics)
    if "defect" in cl:
        return _detect_defect_archetype(deck, relics)
    if "regent" in cl:
        return _detect_regent_archetype(deck, relics)
    if "silent" in cl:
        return _detect_silent_archetype(deck, relics)
    return "generic"


def _detect_ironclad_archetype(deck: list[str], relics: list[str]) -> str:
    """Detect dominant Ironclad archetype from deck and relics."""
    return _detect_from_archetypes(deck, relics, IRONCLAD_ARCHETYPES)


def _detect_necrobinder_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, NECROBINDER_ARCHETYPES)


def _detect_defect_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, DEFECT_ARCHETYPES)


def _detect_regent_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, REGENT_ARCHETYPES)


def _detect_silent_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, SILENT_ARCHETYPES)


def _archetype_match_score(arch: dict, deck_set: set[str], relic_set: set[str]) -> int:
    """Single archetype bucket score from deck + relic overlap."""
    score = 0
    for sig in arch.get("signals", []):
        if any(sig.lower() in d for d in deck_set):
            score += 3
    for card in arch.get("early", []) + arch.get("mid", []) + arch.get("high", []):
        if any(card.lower() in d for d in deck_set):
            score += 1
    for rel in arch.get("relics", []):
        if rel.lower() in relic_set:
            score += 1
    return score


def _detect_from_archetypes(
    deck: list[str], relics: list[str], archetypes: dict
) -> str:
    """Generic archetype detection from signals/cards/relics."""
    relic_set = {r.lower() for r in relics}
    deck_set = {c.lower() for c in deck}
    scores = {
        name: _archetype_match_score(arch, deck_set, relic_set)
        for name, arch in archetypes.items()
    }
    best = max(scores.items(), key=lambda x: x[1])
    return best[0] if best[1] >= 2 else "generic"


# Necrobinder survival picks; Defect claw core; Silent deck-thin tools
_NECRO_SURVIVAL_CARDS = [CARD_PULL_AGGRO, "Delay", "Negative Pulse", "Shroud", "Death's Door"]
_CLAW_CORE_CARDS = ["Claw", "Scrape", CARD_ALL_FOR_ONE]
_SILENT_THIN_DECK_CARDS = ["Tactician", "Acrobatics", "Prepared", "Reflex"]


def _ironclad_archetype_priority(arch: dict, norm: str, score: int, reasons: list[str]) -> int:
    if not arch:
        return score
    if _norm_in_card_list(norm, arch.get("early", [])):
        reasons.append("Early-game priority")
        return score + 35
    if _norm_in_card_list(norm, arch.get("mid", [])):
        reasons.append("Mid-game priority")
        return score + 40
    if _norm_in_card_list(norm, arch.get("high", [])):
        reasons.append("High-commitment payoff")
        return score + 45
    return score


def _ironclad_crossover_bonus(norm: str, archetype: str, score: int, reasons: list[str]) -> int:
    for cross_card, archs in IRONCLAD_CROSSOVER.items():
        if cross_card.lower() in norm or norm in cross_card.lower():
            if archetype in archs:
                reasons.append("Cross-archetype value")
                return score + 15
            break
    return score


def _ironclad_strike_adjustments(
    archetype: str,
    norm: str,
    card_name: str,
    deck: list[str],
    score: int,
    reasons: list[str],
) -> int:
    if archetype != "strike":
        return score
    strike_count = _count_strikes(deck)
    if CARD_PERFECTED_STRIKE.lower() in norm or CARD_PERFECTED_STRIKE in card_name:
        score += 20
        if strike_count >= 5:
            score += 10
        reasons.append("Core Strike card")
    if "strike" in norm and strike_count >= 4:
        score += 5
        reasons.append("Strike synergy")
    if strike_count >= 8 and "strike" in norm and "perfected" not in norm:
        score -= 10
        reasons.append(REASON_DECK_BLOAT)
    return score


def _ironclad_exhaust_finisher_bonus(
    archetype: str, norm: str, deck: list[str], score: int, reasons: list[str]
) -> int:
    if archetype != "exhaust":
        return score
    has_finisher = any(_deck_contains(deck, f) for f in IRONCLAD_EXHAUST_FINISHERS)
    if has_finisher:
        return score
    for fin in IRONCLAD_EXHAUST_FINISHERS:
        if fin.lower() in norm:
            reasons.append("Finisher needed")
            return score + 25
    return score


def _ironclad_relic_adjustments(
    card_name: str, norm: str, deck: list[str], relics: list[str], score: int, reasons: list[str]
) -> int:
    relic_set = {r.lower() for r in relics}
    if "strike dummy" in relic_set and "strike" in norm:
        score += 10
        reasons.append("Strike Dummy synergy")
    if "charon's ashes" in relic_set or "forgotten soul" in relic_set:
        info = lookup_card(card_name)
        desc = (info or {}).get("description", "")
        if _deck_contains(deck, "Corruption") and desc and "exhaust" in desc.lower():
            score += 5
    return score


def _ironclad_demon_form_adjustments(archetype: str, norm: str, score: int, reasons: list[str]) -> int:
    if "demon form" not in norm:
        return score
    if archetype == "exhaust":
        score -= 5
        reasons.append("Energy-heavy, Exhaust prefers cheap")
    elif archetype == "strike":
        score += 10
        reasons.append("Energy for Perfected Strike")
    return score


def _tier_from_archetype_score(score: int) -> str:
    """Letter tier when Mobalytics data is missing (heuristic from composite score)."""
    if score >= 80:
        return "S"
    if score >= 65:
        return "A"
    if score >= 50:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def _blend_mobalytics_tier(
    character: str, card_name: str, arch_score: int, reason: str
) -> tuple[int, str, str]:
    """Returns (final_score, display_tier, reason_text)."""
    mb_tier = mobalytics_tier_for(character, card_name)
    if mb_tier and mb_tier in MOBALYTICS_TIER_SCORE:
        mob_num = MOBALYTICS_TIER_SCORE[mb_tier]
        blended = int(
            round(
                MOBALYTICS_BLEND_WEIGHT * mob_num
                + (1.0 - MOBALYTICS_BLEND_WEIGHT) * arch_score
            )
        )
        blended = min(100, max(0, blended))
        mb_note = f"Mobalytics {mb_tier}-tier"
        merged = f"{mb_note}; {reason}" if reason else mb_note
        return blended, mb_tier, merged
    return arch_score, _tier_from_archetype_score(arch_score), reason


def _score_ironclad_card(
    card_name: str,
    archetype: str,
    deck: list[str],
    relics: list[str],
) -> tuple[int, str]:
    """Score a single card for Ironclad. Returns (score, reason)."""
    score = 50  # base
    reasons: list[str] = []
    norm = _normalize_name(card_name)
    arch = IRONCLAD_ARCHETYPES.get(archetype, {})

    score = _ironclad_archetype_priority(arch, norm, score, reasons)
    score = _ironclad_crossover_bonus(norm, archetype, score, reasons)
    score = _ironclad_strike_adjustments(archetype, norm, card_name, deck, score, reasons)
    score = _ironclad_exhaust_finisher_bonus(archetype, norm, deck, score, reasons)
    score = _ironclad_relic_adjustments(card_name, norm, deck, relics, score, reasons)
    score = _ironclad_demon_form_adjustments(archetype, norm, score, reasons)

    reason = "; ".join(reasons) if reasons else "Neutral pick"
    return (min(100, max(0, score)), reason)


def _score_generic_card(_card_name: str) -> tuple[int, str]:
    """Generic scoring when character/archetype not supported."""
    return (50, "Generic pick")


def _score_character_card(
    character: str,
    card_name: str,
    archetype: str,
    deck: list[str],
    relics: list[str],
) -> tuple[int, str]:
    """Route to character-specific scorer."""
    cl = character.lower()
    if "ironclad" in cl:
        return _score_ironclad_card(card_name, archetype, deck, relics)
    if "necrobinder" in cl:
        return _score_from_archetypes(card_name, archetype, deck, relics, NECROBINDER_ARCHETYPES)
    if "defect" in cl:
        return _score_from_archetypes(card_name, archetype, deck, relics, DEFECT_ARCHETYPES)
    if "regent" in cl:
        return _score_from_archetypes(card_name, archetype, deck, relics, REGENT_ARCHETYPES)
    if "silent" in cl:
        return _score_from_archetypes(card_name, archetype, deck, relics, SILENT_ARCHETYPES)
    return _score_generic_card(card_name)


def _score_from_archetypes(
    card_name: str,
    archetype: str,
    deck: list[str],
    _relics: list[str],
    archetypes: dict,
) -> tuple[int, str]:
    """Generic scoring from archetype priority lists."""
    score = 50
    reasons: list[str] = []
    norm = _normalize_name(card_name)

    arch = archetypes.get(archetype, {})
    score = _ironclad_archetype_priority(arch, norm, score, reasons)

    # Necrobinder: Block is always important (low base HP)
    if archetype in ("doom", "osty"):
        if _norm_in_card_list(norm, _NECRO_SURVIVAL_CARDS):
            score += 5
            reasons.append("Block/survival priority")

    # Defect Claw: avoid bloat
    if archetype == "claw" and len(deck) >= 25:
        if _norm_in_card_list(norm, _CLAW_CORE_CARDS):
            score += 5
        elif "claw" not in norm and "scrape" not in norm:
            score -= 5
            reasons.append(REASON_DECK_BLOAT)

    # Silent Sly: keep deck thin
    if archetype == "sly" and len(deck) >= 20:
        if _norm_in_card_list(norm, _SILENT_THIN_DECK_CARDS):
            score += 5
        else:
            score -= 5
            reasons.append(REASON_DECK_BLOAT)

    reason = "; ".join(reasons) if reasons else "Neutral pick"
    return (min(100, max(0, score)), reason)


def recommend(
    character: str,
    deck: list[str],
    relics: list[str],
    options: list[str],
) -> RewardRecommendation:
    """
    Score each offered card and return recommendations.
    """
    if not options:
        return RewardRecommendation(
            recommendations=[],
            best_card="",
            archetype="generic",
        )

    archetype = _detect_archetype(character, deck, relics)

    scored: list[CardRecommendation] = []
    for card_name in options:
        arch_score, arch_reason = _score_character_card(
            character, card_name, archetype, deck, relics
        )
        score, tier, reason = _blend_mobalytics_tier(
            character, card_name, arch_score, arch_reason
        )
        scored.append(CardRecommendation(name=card_name, score=score, tier=tier, reason=reason))

    scored.sort(key=lambda r: r.score, reverse=True)
    best = scored[0].name if scored else ""

    warnings: list[str] = []
    if archetype == "strike" and _count_strikes(deck) >= 8:
        warnings.append("Strike deck bloat: avoid weak Strikes")
    if archetype == "exhaust":
        has_corruption = _deck_contains(deck, "Corruption")
        has_dark_embrace = _deck_contains(deck, "Dark Embrace")
        has_feel_no_pain = _deck_contains(deck, "Feel No Pain")
        if has_corruption and (not has_dark_embrace or not has_feel_no_pain):
            warnings.append("Exhaust: prioritize Dark Embrace / Feel No Pain")

    return RewardRecommendation(
        recommendations=scored,
        best_card=best,
        archetype=archetype,
        warnings=warnings,
    )
