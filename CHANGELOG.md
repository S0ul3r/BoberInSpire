# Changelog

## [1.1.0] – 2026-03-16

### Added
- **Card reward advisor** – ranks “Choose a Card” options using [Mobalytics](https://mobalytics.gg/slay-the-spire-2/tier-lists/cards) S/A/B/C/D tiers per character, blended with deck / archetype heuristics (`data/tier_lists/mobalytics_cards.json`).
- README screenshot for card-pick UI.

### Fixed
- **Ghost mode (F9)** – reliable toggle back to interactive overlay (Win32 `SWP_FRAMECHANGED`, correct HWNDs, debounce, avoid double F9 handler when global hotkey is active).
- **Mod install layout** – DLL / PCK / JSON target the game’s flat `mods\` folder (STS2 v0.99+), not `mods\BoberInSpire\`. Installer and `build.bat` aligned.
- **Release bundle** – `build.bat` uses a clean `dist`, skips `__pycache__` and local `data\dll dump`, copies `.pck` from the correct `mods\` path when present.

### Changed
- Code quality: shared codex fuzzy lookup (`utils`), removed unused imports, `strategy` imports combat constants from `combat_engine`.

## [1.0.0] – initial release

- Real-time combat overlay, relic summaries, JSON export mod, Windows installer.
