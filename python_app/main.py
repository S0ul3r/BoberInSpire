from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data_parser import load_game_state, load_reward_state
from .file_watcher import GameStateWatcher, RewardStateWatcher
from .models import GameState
from .overlay import CombatOverlay
from .paths import DEFAULT_STATE_FILE, DEFAULT_REWARD_FILE


def create_test_reward_file(reward_path: Path) -> None:
    """Create a test reward JSON so you can verify the CARD REWARD section appears in overlay."""
    reward_path.parent.mkdir(parents=True, exist_ok=True)
    test_data = {
        "type": "card_reward",
        "character": "Ironclad",
        "deck": ["Strike", "Strike", "Strike", "Defend", "Defend"],
        "relics": ["Burning Blood"],
        "options": ["Bash", "Iron Wave", "Pommel Strike"],
    }
    with open(reward_path, "w", encoding="utf-8") as f:
        json.dump(test_data, f, indent=2)
    print(f"[BoberInSpire] Test reward file created: {reward_path}")
    print("[BoberInSpire] If overlay shows CARD REWARD section, Python side works. If not, mod may not write the file.")


def run_overlay(
    state_file: str,
    watch: bool,
    reward_file: str | None = None,
    test_reward: bool = False,
    debug: bool = False,
):
    """Launch the overlay, optionally watching combat and reward files for live updates."""
    path = Path(state_file).resolve()
    reward_path = Path(reward_file or DEFAULT_REWARD_FILE).resolve()
    if test_reward:
        create_test_reward_file(reward_path)
    print(f"[BoberInSpire] Starting overlay, watching: {path}")

    watcher: GameStateWatcher | None = None
    reward_watcher: RewardStateWatcher | None = None

    def cleanup():
        overlay._stop_reward_polling()
        if watcher:
            watcher.stop()
        if reward_watcher:
            reward_watcher.stop()

    overlay = CombatOverlay(on_close=cleanup, debug=debug)
    overlay.set_reward_file_path(str(reward_path))

    overlay.root.update_idletasks()
    overlay.root.lift()
    overlay.root.attributes("-topmost", True)

    if path.exists():
        try:
            initial_state = load_game_state(path)
            overlay.update_state(initial_state)
        except Exception as exc:
            overlay.status_label.config(text=f"Error: {exc}")
    elif reward_path.exists():
        try:
            reward_data = load_reward_state(reward_path)
            if reward_data and reward_data.get("options"):
                overlay.update_reward_state(reward_data)
        except Exception:
            pass

    if watch:
        def on_update(state: GameState):
            overlay.root.after(0, overlay.update_state, state)

        def on_error(msg: str):
            overlay.root.after(
                0, lambda: overlay.status_label.config(text=f"Error: {msg}")
            )

        def on_reward_update(data: dict):
            overlay.root.after(0, overlay.update_reward_state, data)

        watcher = GameStateWatcher(path, on_update=on_update, on_error=on_error)
        watcher.start()
        reward_watcher = RewardStateWatcher(reward_path, on_update=on_reward_update)
        reward_watcher.start()
        overlay.start_continuous_reward_polling()
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
    parser.add_argument(
        "--test-reward",
        action="store_true",
        help="Create test reward file before starting overlay (to verify CARD REWARD section)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show debug panel in overlay (reward file status, parsed options)",
    )

    args = parser.parse_args()

    if args.cli:
        run_cli(args.file)
    else:
        run_overlay(
            args.file,
            watch=not args.no_watch,
            test_reward=args.test_reward,
            debug=args.debug,
        )


if __name__ == "__main__":
    main()
