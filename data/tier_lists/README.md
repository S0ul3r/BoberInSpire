# Card tier lists (Mobalytics snapshot)

- **Source:** [Slay the Spire 2 Card Tier List – Mobalytics](https://mobalytics.gg/slay-the-spire-2/tier-lists/cards)
- **File:** `mobalytics_cards.json` — tiers **S** / **A** / **B** / **C** / **D** per character (Ironclad, Silent, Regent, Necrobinder, Defect).
- **Used by:** `python_app/reward_advisor.py` — overlay **CARD REWARD** shows each card’s **Mobalytics tier** when the name matches (upgrades like `Card+` are normalized to `Card`). Scores blend tier list (~55%) with the existing archetype / build-guide heuristics (~45%).
- **`data/build_guides/`:** Still used for archetype detection and card priorities; tier JSON adds a global power baseline per card.

**Updating:** When Mobalytics changes, edit `mobalytics_cards.json` (or replace the `characters` object). Fetching the page as markdown often gives copy-pasteable tier blocks.

Preliminary / Early Access list — see Mobalytics methodology on the site.
