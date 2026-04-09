# Card tier lists

## Mobalytics (`mobalytics_cards.json`)

- **Source:** [Mobalytics STS2 card tiers](https://mobalytics.gg/slay-the-spire-2/tier-lists/cards)
- Tiers **S** / **A** / **B** / **C** / **D** per character.
- Refresh pipeline command from repo root:
  - `python scripts/update_build_and_tier_data.py`
  - (currently this updates STS2 wiki tiers + build guides + generated archetype indexes and best-effort Mobalytics Ironclad builds)

## slaythespire-2.com (`slaythespire2_com_cards.json`)

- **Source:** [STS2 Wiki card tier page](https://slaythespire-2.com/card-tier)
- **Refresh (recommended):** from repo root, `python scripts/scrape_sts2_wiki_tiers.py` (network) — regenerates the JSON from the live page.
- **Manual:** you can still edit `slaythespire2_com_cards.json` directly (same `characters` → `S`/`A`/… shape as Mobalytics). Includes **F** where the site uses it.

## Advisor blending

`python_app/reward_advisor.py` averages numeric scores from **each tier source that recognizes the card** (Mobalytics and/or wiki), then blends that average **~55%** with archetype heuristics **~45%**. The overlay shows **M:** / **W:** tier letters next to the combined score when known.
