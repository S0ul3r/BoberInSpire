## BoberInSpire – Slay the Spire 2 Combat Assistant

![Combat Assistant overlay](data/media/overlay_UI.png)

BoberInSpire is a **hybrid C# + Python assistant** for Slay the Spire 2.
A custom C# mod exports the current combat / merchant state to JSON, and a Python overlay analyzes it and shows real‑time information in a separate, semi‑transparent window.

### Main features

- **Real-time combat state** – mod exports hand, energy, block, and enemy data to JSON.
- **Damage and block summary** – overlay shows net damage and per-enemy incoming damage.
- **Relic summaries** – combat-relevant relic effects shown in a compact list.
- **Semi-transparent overlay** – always-on-top window with ghost (click-through) mode (F9).
- **Card reward advisor** – on the post-combat **Choose a Card** screen, ranks the three offered cards using **[Mobalytics](https://mobalytics.gg/slay-the-spire-2/tier-lists/cards) S/A/B/C/D tier lists** (per character) **combined** with deck/archetype heuristics from local build guides. The overlay shows **BEST**, tier letter, blended score, and a short reason (e.g. `Mobalytics B-tier; …`).
- **Multi-language support** – works with any game language (Russian, Japanese, Chinese, and 11 more). Card and relic names are automatically translated to English for matching. See [Language support](#language-support).

#### Card pick advisor (screenshot)

![Card reward advisor with Mobalytics tiers](data/media/cardpick_UI.png)

The mod writes reward options to `%APPDATA%\SlayTheSpire2\bober_reward_state.json`; the overlay reads them and updates the **CHOOSE A CARD / CARD REWARD** section. Tier data lives in `data/tier_lists/mobalytics_cards.json` (see `data/tier_lists/README.md` to refresh from Mobalytics).

### Installing using installer

Download the **Windows installer** (`BoberInSpire_Setup_<version>.exe`) from the project **Releases** page. **No Python or other tools required** — everything is bundled.

#### Prerequisites

- **Slay the Spire 2** installed (Steam).

That's it.

#### Run the installer

1. **Close Slay the Spire 2** before installing.
2. Run **`BoberInSpire_Setup_<version>.exe`**.
3. The installer **auto-detects your game folder** from Steam. If the path is wrong, correct it manually.
4. Finish the installation. The mod files are copied to the game automatically.

#### Turn the mod on in-game (once)

1. Start **Slay the Spire 2** from Steam.
2. Open **Settings → Modding / Mods**.
3. Enable **BoberInSpire**. Restart the game if prompted.

#### Start the overlay

Launch **BoberInSpire Overlay** from the Start Menu or desktop shortcut. Leave it running while you play.

#### If you did not use "copy mod"

Manually copy from the install directory's **`Mod`** folder into **`<Slay the Spire 2>\mods\`**:

- `BoberInSpire.dll`
- `BoberInSpire.pck`
- `BoberInSpire.json`

#### Quick troubleshooting

| Issue | Try this |
|--------|-----------|
| Overlay does not start | Re-run the installer. If the problem persists, open an issue with the error message. |
| Mod missing in game | Check that the three files are in `...\Slay the Spire 2\mods\` (flat, not a subfolder). In **Settings → Modding**, enable BoberInSpire and restart the game. |
| Card advisor shows wrong picks | Your game might use a language not yet extracted. See [Language support](#language-support). |

---

### Language support

The overlay works with **any game language**. On first launch it automatically reads the game's translation files and creates a mapping from localized card/relic names back to English — this is needed because tier lists and archetype data use English names internally.

**Supported languages** (auto-detected): English, German, Spanish, French, Italian, Japanese, Korean, Polish, Portuguese (BR), Russian, Spanish (Latin America), Thai, Turkish, Chinese (Simplified).

If auto-extraction fails (e.g. the game is not found), the overlay still works but only matches English card names. You can trigger extraction manually:

```bat
python scripts/extract_translations.py
```

Or specify the game path:

```bat
python scripts/extract_translations.py --game-dir "D:\Steam\steamapps\common\Slay the Spire 2"
```

---

### Data source & acknowledgments

Card and relic data used by the overlay comes from **[Spire Codex](https://spire-codex.com/)**, the Slay the Spire 2 database and API built from decompiled game data. Many thanks to the Spire Codex project for making this data available.

- **Website:** [https://spire-codex.com/](https://spire-codex.com/)
- **Repository:** [https://github.com/ptrlrd/spire-codex](https://github.com/ptrlrd/spire-codex)

**Card reward tiers** are based on Mobalytics' [Slay the Spire 2 card tier list](https://mobalytics.gg/slay-the-spire-2/tier-lists/cards) (Early Access / preliminary list — update the JSON when their rankings change).

---

## Run locally (development)

1. **Build the mod** (with STS2 **closed**):

   ```bat
   dotnet build STS2Mods\sts2_example_mod\ExampleMod.csproj -c Debug
   ```

   This builds **BoberInSpire.dll**, **BoberInSpire.pck**, and **BoberInSpire.json** into your STS2 **`mods\`** folder. The project file is still `ExampleMod.csproj`; the mod name and output DLL are **BoberInSpire**.

2. **Install Python deps** (once):

   ```bat
   pip install watchdog keyboard pyinstaller
   ```

3. **Run the overlay from source**:

   ```bat
   py -3 -m python_app.main
   ```

4. Start STS2 from Steam. In **Settings → Modding**, enable **BoberInSpire**, then enter combat. The overlay watches `%APPDATA%\SlayTheSpire2\bober_combat_state.json` (combat) and `bober_reward_state.json` (card rewards) and updates in real time.

> If the mod build fails with "file is being used by another process", **close STS2** and run the build again.

---

## Release package (installer)

```bat
build.bat
iscc installer.iss
```

`build.bat` does the following:
1. Builds the C# mod (`dotnet build`)
2. Bundles the Python overlay into a standalone exe (`pyinstaller overlay.spec`)
3. Copies data files (card DB, tier lists)
4. Copies mod files (DLL, PCK, JSON)
5. Extracts translations from the game PCK (if game is found)

The result is `dist\BoberInSpire\` — a self-contained folder with `BoberInSpire.exe` and everything it needs. `iscc installer.iss` packages it into a setup wizard.

---

## Optional: custom game path

If STS2 is not in the default location, create **`STS2Mods\sts2_example_mod\local.props`**:

```xml
<Project>
  <PropertyGroup>
    <STS2GamePath>C:\Path\To\Your\Slay the Spire 2</STS2GamePath>
    <GodotExePath>C:\Path\To\Godot_mono.exe</GodotExePath>
  </PropertyGroup>
</Project>
```

---

## Overlay controls

- **Drag window** – click and drag the custom title bar.
- **Resize** – drag the small grip in the bottom-right corner.
- **Close** – click the **X** in the title bar.
- **Ghost mode (click-through)** – click the **eye** icon or press **F9**; clicks pass through to the game. Press F9 again to return to interactive mode.
