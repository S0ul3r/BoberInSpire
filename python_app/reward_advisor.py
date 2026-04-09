"""
Card reward advisor: scores offered cards from deck, Python archetype tables, tier lists,
and scraped slaythespire-2.com build guides under ``data/build_guides/<character>/``.
Overlay copy is intentionally short; set env ``BOBER_REWARD_DEBUG=1`` for verbose
reason strings and console deck logging.

Mobalytics-style priorities live in ``IRONCLAD_ARCHETYPES`` (etc.), not parsed from
``guide.md``. Wiki build JSON (``wiki_builds.json``) supplies per-build core / acquisition /
flex lists; when the deck matches a build strongly enough, offered cards that fit that
build get an extra archetype-score bonus before tier-list blending.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from .card_db import lookup_card

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BUILD_GUIDES_DIR = DATA_DIR / "build_guides"
MOBALYTICS_TIERS_PATH = DATA_DIR / "tier_lists" / "mobalytics_cards.json"
STS2_WIKI_TIERS_PATH = DATA_DIR / "tier_lists" / "slaythespire2_com_cards.json"

# Deck ↔ wiki build affinity (sum of weighted overlaps); below this → no build-specific bonus
WIKI_BUILD_MIN_AFFINITY = 5.0
# Extra archetype points before tier blend (capped with overall score in _score_character_card path)
_WIKI_BONUS_CORE = 14
_WIKI_BONUS_FLEX = 10
_WIKI_BONUS_PRIORITY: dict[str, int] = {
    "must_pick": 26,
    "high": 16,
    "medium": 9,
    "low": 6,
}

# Numeric anchors S–D shared by Mobalytics + slaythespire-2.com; F only on wiki list.
TIER_LETTER_SCORE: dict[str, int] = {
    "S": 92,
    "A": 78,
    "B": 64,
    "C": 50,
    "D": 36,
    "F": 22,
}
# Average tier-list numeric (Mobalytics + wiki when both exist) vs archetype heuristic
COMBINED_TIER_LIST_WEIGHT = 0.55
ARCHETYPE_SCORE_WEIGHT = 0.45

# Reward screen sometimes offers already-upgraded cards (name ends with "+"); bump final score.
OFFERED_UPGRADE_SCORE_BONUS = 10

REWARD_ADVISOR_DEBUG = os.environ.get("BOBER_REWARD_DEBUG", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Overlay: keep recommendation blurbs readable but not essay-long (verbose → BOBER_REWARD_DEBUG=1)
REWARD_OVERLAY_REASON_MAX = 140


def _neutral_card_reason(archetype: str, deck_len: int, uniq: int) -> str:
    """Explain a pick that got no archetype early/mid/high bonuses (tier lists may still apply)."""
    if REWARD_ADVISOR_DEBUG:
        if archetype == "generic":
            return (
                f"No strong archetype match yet ({deck_len} cards, {uniq} unique names in export); "
                "tier list dominates — add signature cards/relics from the build guide to tune advice"
            )
        return (
            f"This card is not in the {archetype} early/mid/high priority lists "
            f"({deck_len} cards, {uniq} unique in export); archetype score stayed at baseline"
        )
    if archetype == "generic":
        return "No build match, score comes from tier lists"
    return (
        f"Not on your {archetype} priority lists — tier grades still move the score."
    )


def _is_overlay_neutral_arch_reason(arch_reason: str) -> bool:
    """True when there is nothing to show beyond tier captions (wiki hints count as non-neutral)."""
    s = (arch_reason or "").strip()
    if not s:
        return True
    if "slaythespire-2.com" in s.lower():
        return False
    for part in s.split(";"):
        p = part.strip()
        if not p:
            continue
        neutral = (
            p.startswith("No build match, score comes from tier lists")
            or p.startswith("Not on your ")
            or p.startswith("No archetype fit")
            or p.endswith("· tiers drive score")
        )
        if not neutral:
            return False
    return True


def _trim_overlay_reason(text: str, max_len: int = REWARD_OVERLAY_REASON_MAX) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _compact_tier_caption(mob_t: str | None, wiki_t: str | None) -> str:
    parts: list[str] = []
    if mob_t:
        parts.append(f"M:{mob_t}")
    if wiki_t:
        parts.append(f"W:{wiki_t}")
    return " · ".join(parts) if parts else "Tiers"


def _maybe_log_reward_debug(
    character: str,
    archetype: str,
    deck: list[str],
    relics: list[str],
    options: list[str],
) -> None:
    if not REWARD_ADVISOR_DEBUG:
        return
    sample = sorted({c for c in deck}, key=str.lower)[:12]
    print(
        "[BoberInSpire reward_advisor]",
        f"character={character!r} archetype={archetype!r}",
        f"deck_n={len(deck)} unique={len(set(c.lower() for c in deck))}",
        f"relics_n={len(relics)} options={options!r}",
        f"deck_sample={sample!r}",
        flush=True,
    )


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

FALLBACK_ARCHETYPES_BY_CHARACTER: dict[str, dict] = {
    "Ironclad": IRONCLAD_ARCHETYPES,
    "Silent": SILENT_ARCHETYPES,
    "Defect": DEFECT_ARCHETYPES,
    "Regent": REGENT_ARCHETYPES,
    "Necrobinder": NECROBINDER_ARCHETYPES,
}


@lru_cache(maxsize=1)
def _load_generated_archetypes_catalog() -> dict[str, dict]:
    """
    Character key -> archetype dict from ``guide_archetypes.json``.
    Falls back to hardcoded tables when generated files are missing.
    """
    out: dict[str, dict] = {}
    if not BUILD_GUIDES_DIR.is_dir():
        return out
    for sub in sorted(BUILD_GUIDES_DIR.iterdir()):
        if not sub.is_dir():
            continue
        path = sub / "guide_archetypes.json"
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        char = raw.get("character")
        arch = raw.get("archetypes")
        if isinstance(char, str) and isinstance(arch, dict):
            out[char] = arch
    return out


def _archetypes_for_character(character: str) -> dict:
    ck = _mobalytics_character_key(character)
    if not ck:
        return {}
    generated = _load_generated_archetypes_catalog().get(ck)
    if isinstance(generated, dict) and generated:
        return generated
    return FALLBACK_ARCHETYPES_BY_CHARACTER.get(ck, {})


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
    mobalytics_tier: str | None = None
    wiki_tier: str | None = None


@dataclass
class RewardRecommendation:
    recommendations: list[CardRecommendation]
    best_card: str
    archetype: str
    warnings: list[str] = field(default_factory=list)
    # Best-matching slaythespire-2.com scraped build for this deck (affinity ≥ WIKI_BUILD_MIN_AFFINITY)
    wiki_build_title: str | None = None
    wiki_build_id: str | None = None


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


def _offered_card_is_upgraded(name: str) -> bool:
    """True if the reward row is an upgraded copy (e.g. Molten Fist+)."""
    s = name.strip()
    return bool(s) and s.endswith("+")


def _fill_tier_index(
    idx: dict[str, str], tier_key: str, names: object, valid_tiers: frozenset[str]
) -> None:
    """Add card names from one tier bucket into idx (lowercase -> tier letter)."""
    if len(tier_key) != 1 or tier_key not in valid_tiers:
        return
    if not isinstance(names, list):
        return
    for n in names:
        if isinstance(n, str) and n.strip():
            idx[n.strip().lower()] = tier_key


_MOB_TIERS = frozenset("SABCD")


@lru_cache(maxsize=1)
def _load_mobalytics_index() -> dict[str, dict[str, str]]:
    """
    character_name -> lowercase card name -> tier letter (S/A/B/C/D).
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
            _fill_tier_index(idx, tier_key, names, _MOB_TIERS)
        out[str(char_name)] = idx
    return out


_WIKI_TIERS = frozenset("SABCDF")


def _collapse_name_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


@lru_cache(maxsize=1)
def _load_sts2_wiki_indexes() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """
    (exact_lower -> tier, collapsed_alnum -> tier) per character for slaythespire-2.com list.
    """
    if not STS2_WIKI_TIERS_PATH.is_file():
        return {}, {}
    try:
        raw = json.loads(STS2_WIKI_TIERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, {}
    exact: dict[str, dict[str, str]] = {}
    collapsed: dict[str, dict[str, str]] = {}
    chars = (raw.get("characters") or {}) if isinstance(raw, dict) else {}
    for char_name, tiers in chars.items():
        if not isinstance(tiers, dict):
            continue
        ex: dict[str, str] = {}
        col: dict[str, str] = {}
        for tier_key, names in tiers.items():
            if not isinstance(names, list):
                continue
            for n in names:
                if not isinstance(n, str) or not n.strip():
                    continue
                lk = n.strip().lower()
                ex[lk] = tier_key.upper()
                col[_collapse_name_key(lk)] = tier_key.upper()
        exact[str(char_name)] = ex
        collapsed[str(char_name)] = col
    return exact, collapsed


def _mobalytics_character_key(character: str) -> str | None:
    """Map exported game character string to JSON key (Ironclad, Silent, ...)."""
    cl = character.lower().replace("_", " ").replace(".", " ")
    if "(" in cl:
        cl = cl.split("(", 1)[0].strip()
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


def wiki_tier_for(character: str, card_name: str) -> str | None:
    """Tier from slaythespire-2.com snapshot (S/A/B/C/D/F), or None."""
    ck = _mobalytics_character_key(character)
    if not ck:
        return None
    exact, collapsed = _load_sts2_wiki_indexes()
    ex = exact.get(ck) or {}
    col = collapsed.get(ck) or {}
    base = _base_card_name(card_name).strip().lower()
    if base in ex:
        return ex[base]
    ck2 = _collapse_name_key(base)
    return col.get(ck2)


@lru_cache(maxsize=1)
def _load_wiki_build_catalog() -> dict[str, list[dict]]:
    """
    Character key (e.g. Ironclad) -> list of build dicts from any ``*_builds.json``
    in each ``build_guides/<folder>/`` directory.
    """
    out: dict[str, list[dict]] = {}
    if not BUILD_GUIDES_DIR.is_dir():
        return out
    for sub in sorted(BUILD_GUIDES_DIR.iterdir()):
        if not sub.is_dir():
            continue
        for path in sorted(sub.glob("*_builds.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            char = raw.get("character")
            builds = raw.get("builds")
            if not isinstance(char, str) or not isinstance(builds, list):
                continue
            bucket = out.setdefault(char, [])
            bucket.extend(b for b in builds if isinstance(b, dict))
    return out


def _guide_card_matches(player_card: str, guide_name: str) -> bool:
    """True if an exported/offered card name matches a wiki guide card name."""
    a = _base_card_name(player_card).strip().lower()
    g = (guide_name or "").strip().lower()
    if not a or not g:
        return False
    if a == g:
        return True
    if _collapse_name_key(a) == _collapse_name_key(g):
        return True
    if len(g) >= 8 and g in a:
        return True
    if len(a) >= 8 and a in g:
        return True
    return False


def _deck_matches_guide_name(deck: list[str], guide_name: str) -> bool:
    return any(_guide_card_matches(c, guide_name) for c in deck)


def _wiki_build_deck_affinity(build: dict, deck: list[str]) -> float:
    """How well the current deck matches one wiki build (higher = stronger)."""
    score = 0.0
    counted: set[str] = set()
    for entry in build.get("core_cards") or []:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in counted:
            continue
        if _deck_matches_guide_name(deck, name):
            counted.add(key)
            score += 5.0
    for row in build.get("card_acquisition_priority") or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in counted:
            continue
        if not _deck_matches_guide_name(deck, name):
            continue
        counted.add(key)
        p = str(row.get("priority") or "").lower()
        score += {"must_pick": 4.0, "high": 2.0, "medium": 1.0, "low": 0.5}.get(p, 1.0)
    return score


def _wiki_best_build_for_deck(character: str, deck: list[str]) -> tuple[dict | None, float]:
    ck = _mobalytics_character_key(character)
    if not ck:
        return None, 0.0
    builds = _load_wiki_build_catalog().get(ck) or []
    if not builds:
        return None, 0.0
    best: dict | None = None
    best_aff = 0.0
    for b in builds:
        aff = _wiki_build_deck_affinity(b, deck)
        # Prefer richer slaythespire-2.com build entries when affinity is close.
        url = str(b.get("url") or "")
        if "slaythespire-2.com" in url:
            aff += 0.25
        if aff > best_aff:
            best_aff = aff
            best = b
    if best is None or best_aff < WIKI_BUILD_MIN_AFFINITY:
        return None, best_aff
    return best, best_aff


def _wiki_offered_card_bonus(build: dict, offered_card: str) -> tuple[int, str]:
    """Extra archetype points if the reward matches this build's card lists."""
    candidates: list[tuple[int, str]] = []
    for entry in build.get("core_cards") or []:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if name and _guide_card_matches(offered_card, name):
            candidates.append((_WIKI_BONUS_CORE, "core card"))
    for row in build.get("card_acquisition_priority") or []:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if not name or not _guide_card_matches(offered_card, name):
            continue
        p = str(row.get("priority") or "").lower()
        pts = _WIKI_BONUS_PRIORITY.get(p, 7)
        candidates.append((pts, p.replace("_", " ")))
    for flex in build.get("flex_cards") or []:
        if not isinstance(flex, dict):
            continue
        name = (flex.get("name") or "").strip()
        if name and _guide_card_matches(offered_card, name):
            candidates.append((_WIKI_BONUS_FLEX, "flex"))
    if not candidates:
        return 0, ""
    best_pts, best_lbl = max(candidates, key=lambda x: x[0])
    title = (build.get("title") or build.get("id") or "build").strip()
    url = str(build.get("url") or "")
    source = "build guide"
    if "slaythespire-2.com" in url:
        source = "slaythespire-2.com"
    elif "mobalytics.gg" in url:
        source = "mobalytics.gg"
    return best_pts, f"{source} «{title}» — {best_lbl}"


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
    archetypes = _archetypes_for_character(character)
    if not archetypes:
        return "generic"
    return _detect_from_archetypes(deck, relics, archetypes)


def _detect_ironclad_archetype(deck: list[str], relics: list[str]) -> str:
    """Detect dominant Ironclad archetype from deck and relics."""
    return _detect_from_archetypes(deck, relics, _archetypes_for_character("Ironclad"))


def _detect_necrobinder_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, _archetypes_for_character("Necrobinder"))


def _detect_defect_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, _archetypes_for_character("Defect"))


def _detect_regent_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, _archetypes_for_character("Regent"))


def _detect_silent_archetype(deck: list[str], relics: list[str]) -> str:
    return _detect_from_archetypes(deck, relics, _archetypes_for_character("Silent"))


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
    if not archetypes:
        return "generic"
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


def _tier_list_numeric_average(character: str, card_name: str) -> tuple[float | None, str | None, str | None]:
    """Average numeric score from Mobalytics and/or STS2wiki tier rows; None if neither hits."""
    mob_t = mobalytics_tier_for(character, card_name)
    wiki_t = wiki_tier_for(character, card_name)
    nums: list[int] = []
    if mob_t and mob_t in TIER_LETTER_SCORE:
        nums.append(TIER_LETTER_SCORE[mob_t])
    if wiki_t and wiki_t in TIER_LETTER_SCORE:
        nums.append(TIER_LETTER_SCORE[wiki_t])
    if not nums:
        return None, mob_t, wiki_t
    return sum(nums) / len(nums), mob_t, wiki_t


def _blend_dual_tier_lists(
    character: str, card_name: str, arch_score: int, arch_reason: str
) -> tuple[int, str, str, str | None, str | None]:
    """
    Combine Mobalytics + slaythespire-2.com tier numerics (average when both exist),
    then blend with archetype score. Returns (final_score, display_tier, reason, mob_t, wiki_t).
    """
    tier_avg, mob_t, wiki_t = _tier_list_numeric_average(character, card_name)
    if tier_avg is not None:
        blended = int(
            round(
                COMBINED_TIER_LIST_WEIGHT * tier_avg
                + ARCHETYPE_SCORE_WEIGHT * arch_score
            )
        )
        blended = min(100, max(0, blended))
        disp = _tier_from_archetype_score(blended)
        cap = _compact_tier_caption(mob_t, wiki_t)
        if REWARD_ADVISOR_DEBUG:
            labels: list[str] = []
            if mob_t:
                labels.append(f"Mobalytics {mob_t}")
            if wiki_t:
                labels.append(f"STS2wiki {wiki_t}")
            src = " + ".join(labels) if len(labels) > 1 else (labels[0] if labels else "tiers")
            merged = _trim_overlay_reason(f"{src} (blend) · {arch_reason}")
        elif _is_overlay_neutral_arch_reason(arch_reason):
            # Short human subtitle (M/W tags stay on the main row only)
            merged = _trim_overlay_reason(arch_reason)
        else:
            merged = _trim_overlay_reason(f"{cap} — {arch_reason}")
        return blended, disp, merged, mob_t, wiki_t
    return (
        arch_score,
        _tier_from_archetype_score(arch_score),
        _trim_overlay_reason(arch_reason) if not REWARD_ADVISOR_DEBUG else arch_reason,
        mob_t,
        wiki_t,
    )


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
    arch = _archetypes_for_character("Ironclad").get(archetype, {})

    score = _ironclad_archetype_priority(arch, norm, score, reasons)
    score = _ironclad_crossover_bonus(norm, archetype, score, reasons)
    score = _ironclad_strike_adjustments(archetype, norm, card_name, deck, score, reasons)
    score = _ironclad_exhaust_finisher_bonus(archetype, norm, deck, score, reasons)
    score = _ironclad_relic_adjustments(card_name, norm, deck, relics, score, reasons)
    score = _ironclad_demon_form_adjustments(archetype, norm, score, reasons)

    uniq = len({c.lower() for c in deck})
    reason = (
        "; ".join(reasons)
        if reasons
        else _neutral_card_reason(archetype, len(deck), uniq)
    )
    return (min(100, max(0, score)), reason)


def _score_generic_card(_card_name: str, deck: list[str]) -> tuple[int, str]:
    """Generic scoring when character/archetype not supported."""
    uniq = len({c.lower() for c in deck})
    return (50, _neutral_card_reason("generic", len(deck), uniq))


def _score_character_card(
    character: str,
    card_name: str,
    archetype: str,
    deck: list[str],
    relics: list[str],
) -> tuple[int, str]:
    """Route to character-specific scorer."""
    ck = _mobalytics_character_key(character)
    if ck == "Ironclad":
        return _score_ironclad_card(card_name, archetype, deck, relics)
    if ck:
        return _score_from_archetypes(
            card_name,
            archetype,
            deck,
            relics,
            _archetypes_for_character(ck),
        )
    return _score_generic_card(card_name, deck)


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

    uniq = len({c.lower() for c in deck})
    reason = (
        "; ".join(reasons)
        if reasons
        else _neutral_card_reason(archetype, len(deck), uniq)
    )
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
            wiki_build_title=None,
            wiki_build_id=None,
        )

    archetype = _detect_archetype(character, deck, relics)
    wiki_build, _wiki_aff = _wiki_best_build_for_deck(character, deck)
    wiki_title: str | None = None
    wiki_id: str | None = None
    if wiki_build:
        wiki_title = wiki_build.get("title") or None
        wiki_id = wiki_build.get("id") or None
    _maybe_log_reward_debug(character, archetype, deck, relics, options)

    scored: list[CardRecommendation] = []
    for card_name in options:
        arch_score, arch_reason = _score_character_card(
            character, card_name, archetype, deck, relics
        )
        if wiki_build:
            wb_pts, wb_note = _wiki_offered_card_bonus(wiki_build, card_name)
            if wb_pts:
                arch_score = min(100, arch_score + wb_pts)
                arch_reason = (
                    f"{arch_reason}; {wb_note}" if arch_reason else wb_note
                )
        score, tier, reason, mob_t, wiki_t = _blend_dual_tier_lists(
            character, card_name, arch_score, arch_reason
        )
        if _offered_card_is_upgraded(card_name):
            score = min(100, score + OFFERED_UPGRADE_SCORE_BONUS)
            tier = _tier_from_archetype_score(score)
            bump_note = f"upgraded offer (+{OFFERED_UPGRADE_SCORE_BONUS})"
            reason = _trim_overlay_reason(
                f"{reason}; {bump_note}" if reason.strip() else bump_note
            )
        scored.append(
            CardRecommendation(
                name=card_name,
                score=score,
                tier=tier,
                reason=reason,
                mobalytics_tier=mob_t,
                wiki_tier=wiki_t,
            )
        )

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
        wiki_build_title=wiki_title,
        wiki_build_id=wiki_id,
    )
