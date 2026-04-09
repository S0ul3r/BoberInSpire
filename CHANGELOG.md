# Changelog

## [1.3.0] – 2026-03-27

### Added
- **React + Tauri overlay** – replaces the old Tkinter window with a semi-transparent WebView shell (`BoberInSpireOverlay.exe`), driven by a local **WebSocket** bridge (`websockets` on Python, port **18765** by default).
- **Overlay settings** – panel and transparency toggles persist via `bober_overlay_settings.json`.
- **Release documentation** – README sections for overlay build/run, installer output paths, and what to upload for GitHub Releases.

### Changed
- **Python entry** – `python_app.main` starts the bridge and, when `BoberInSpireOverlay.exe` is present next to the install (or `BOBER_OVERLAY_EXE` is set), launches the Tauri UI automatically.
- **Repository hygiene** – overlay UI ignore rules consolidated into the root `.gitignore`.

### Removed
- **Legacy Tkinter overlay** – `python_app/overlay.py` removed; view model lives in `overlay_view_model.py`, network host in `overlay_host.py`.

## [1.2.0] – 2026-03-24

### Added
- **Player install flow in README** – added a non-programmer-friendly installer guide and simplified launch steps for users who only want to play with the overlay/mod.
- **Upgraded card reward boost** – card reward advisor now applies a flat `+10` score bump to upgraded offers (e.g. `Molten Fist+`) and surfaces it in the recommendation reason.
- Reddit post package updated in `docs/reddit_post.md` with direct screenshot links for combat overlay and card pick advisor.

### Fixed
- **Freeze / stall risk during export** – debounced export now defers execution to the Godot main thread instead of reading game state from a timer thread.
- **Localization formatting errors** – exporter now resolves formatted text with dynamic variables (`DynamicVarSet`) for cards/relics, preventing repeated formatting failures in combat logs.
- **Mod loading guidance** – docs now reflect current STS2 behavior (`<game>\mods\` + in-game mod toggle), with GUMM treated as optional.

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
