from __future__ import annotations

import argparse
from pathlib import Path

from .data_parser import load_game_state
from .file_watcher import GameStateWatcher
from .models import GameState
from .overlay import CombatOverlay


import os

_APPDATA = os.getenv("APPDATA", "")
DEFAULT_STATE_FILE = os.path.join(_APPDATA, "SlayTheSpire2", "bober_combat_state.json")


def run_overlay(state_file: str, watch: bool):
    """Launch the overlay, optionally watching a file for live updates."""
    path = Path(state_file).resolve()
    print(f"[BoberInSpire] Starting overlay, watching: {path}")

    watcher: GameStateWatcher | None = None

    def cleanup():
        if watcher:
            watcher.stop()

    overlay = CombatOverlay(on_close=cleanup)

    overlay.root.update_idletasks()
    overlay.root.lift()
    overlay.root.attributes("-topmost", True)

    if path.exists():
        try:
            initial_state = load_game_state(path)
            overlay.update_state(initial_state)
        except Exception as exc:
            overlay.status_label.config(text=f"Error: {exc}")

    if watch:
        def on_update(state: GameState):
            overlay.root.after(0, overlay.update_state, state)

        def on_error(msg: str):
            overlay.root.after(
                0, lambda: overlay.status_label.config(text=f"Error: {msg}")
            )

        watcher = GameStateWatcher(path, on_update=on_update, on_error=on_error)
        watcher.start()
        overlay.status_label.config(text=f"Watching {path.name}...")

    print("[BoberInSpire] Overlay ready. Look for the dark window at top-left (or press Alt+Tab).")
    overlay.root.after(100, lambda: (overlay.root.lift(), overlay.root.attributes("-topmost", True)))
    overlay.run()


def run_cli(state_file: str):
    """Print combat calculations to stdout (no GUI)."""
    from .combat_engine import calculate_all_enemies, calculate_incoming_damage

    state = load_game_state(state_file)
    p = state.player

    print(f"Turn {state.turn}")
    print(f"Player  HP:{p.hp}/{p.max_hp}  Energy:{p.energy}  STR:{p.strength}  DEX:{p.dexterity}")
    if p.block > 0:
        print(f"Block: {p.block}")
    print(f"Hand: {', '.join(c.name for c in state.hand)}")
    print("-" * 50)

    incoming = calculate_incoming_damage(state)
    if incoming.total_incoming > 0:
        print("\n--- INCOMING DAMAGE ---")
        for ei in incoming.per_enemy:
            if ei.total_damage > 0:
                print(f"  {ei.name:<20s}  {ei.total_damage} dmg")
            else:
                print(f"  {ei.name:<20s}  {ei.move_type}")
        print(f"  Total incoming: {incoming.total_incoming}")
        print(f"  Block: {incoming.player_block}")
        print(f"  NET damage: {incoming.net_damage}  -> HP: {incoming.expected_hp}")

    results = calculate_all_enemies(state)
    for r in results:
        tag = " ** LETHAL **" if r.is_lethal else ""
        print(f"\nVS {r.enemy_name} (HP: {r.enemy_hp}){tag}")
        for dr in r.per_card:
            dmg = f"{dr.final_damage}x{dr.hits}" if dr.hits > 1 else str(dr.total_damage)
            print(f"  {dr.card_name:<20s}  ->  {dmg} dmg  ({dr.energy_spent} energy)")
        print(f"  TOTAL: {r.total_damage} dmg  |  Energy left: {r.energy_remaining}")
        if r.is_lethal:
            print(f"  Overkill: {r.overkill}")

    if state.relics:
        print("\n--- RELICS ---")
        for relic in state.relics:
            desc = relic.description or ""
            if desc:
                print(f"  {relic.name}: {desc}")
            else:
                print(f"  {relic.name}")


def main():
    parser = argparse.ArgumentParser(
        prog="BoberInSpire",
        description="Slay the Spire 2 Combat Assistant",
    )
    parser.add_argument(
        "-f", "--file",
        default=DEFAULT_STATE_FILE,
        help="Path to the game state JSON file",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode (no overlay)",
    )
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Don't watch the file for changes (overlay mode)",
    )

    args = parser.parse_args()

    if args.cli:
        run_cli(args.file)
    else:
        run_overlay(args.file, watch=not args.no_watch)


if __name__ == "__main__":
    main()
