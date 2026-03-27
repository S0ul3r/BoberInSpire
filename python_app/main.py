from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .data_parser import load_game_state, load_reward_state
from .file_watcher import GameStateWatcher, RewardStateWatcher
from .models import GameState
from .overlay_host import (
    DEFAULT_WS_HOST,
    DEFAULT_WS_PORT,
    OverlayHost,
    resolve_overlay_exe,
)


_APPDATA = os.getenv("APPDATA", "")
DEFAULT_STATE_FILE = os.path.join(_APPDATA, "SlayTheSpire2", "bober_combat_state.json")
DEFAULT_REWARD_FILE = os.path.join(_APPDATA, "SlayTheSpire2", "bober_reward_state.json")


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
    """Start WebSocket bridge and Tauri overlay; optionally watch combat and reward JSON files."""
    path = Path(state_file).resolve()
    reward_path = Path(reward_file or DEFAULT_REWARD_FILE).resolve()
    if test_reward:
        create_test_reward_file(reward_path)

    ws_port = int(os.environ.get("BOBER_OVERLAY_WS_PORT", str(DEFAULT_WS_PORT)))
    ws_host = os.environ.get("BOBER_OVERLAY_WS_HOST", DEFAULT_WS_HOST)
    ws_url = f"ws://{ws_host}:{ws_port}"

    host = OverlayHost(host=ws_host, port=ws_port, debug=debug)
    host.start()
    host.set_reward_file_path(str(reward_path))

    watcher: GameStateWatcher | None = None
    reward_watcher: RewardStateWatcher | None = None
    overlay_proc: subprocess.Popen | None = None

    def cleanup_watchers() -> None:
        if watcher:
            watcher.stop()
        if reward_watcher:
            reward_watcher.stop()

    def shutdown_and_exit() -> None:
        cleanup_watchers()
        if overlay_proc and overlay_proc.poll() is None:
            overlay_proc.terminate()
        time.sleep(0.1)
        os._exit(0)

    host.set_on_shutdown(shutdown_and_exit)

    exe = resolve_overlay_exe()
    forced = os.environ.get("BOBER_OVERLAY_EXE", "").strip()
    if forced and not exe:
        print(
            f"[BoberInSpire] BOBER_OVERLAY_EXE is set but file not found: {forced!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if exe:
        env = {**os.environ, "BOBER_OVERLAY_WS_URL": ws_url}
        try:
            overlay_proc = subprocess.Popen(
                [str(exe)],
                env=env,
                cwd=str(exe.parent),
            )
        except OSError as exc:
            print(f"[BoberInSpire] Failed to start overlay UI: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"[BoberInSpire] Overlay UI: {exe}")
    else:
        print(
            "[BoberInSpire] No Tauri overlay binary found. "
            "Build with: cd overlay-ui && npm install && npm run tauri build\n"
            f"           Or set BOBER_OVERLAY_EXE. WebSocket bridge: {ws_url}"
        )

    def watch_child() -> None:
        if overlay_proc is None:
            return
        code = overlay_proc.wait()
        cleanup_watchers()
        print(f"[BoberInSpire] Overlay UI exited ({code}). Shutting down bridge.")
        os._exit(0)

    if overlay_proc is not None:
        threading.Thread(target=watch_child, name="OverlayChildWatch", daemon=True).start()

    print(f"[BoberInSpire] Watching: {path}")
    if path.exists():
        try:
            initial_state = load_game_state(path)
            host.update_state(initial_state)
        except Exception as exc:
            print(f"[BoberInSpire] Initial load error: {exc}")
            host.notify_update()
    elif reward_path.exists():
        try:
            reward_data = load_reward_state(reward_path)
            if reward_data and reward_data.get("options"):
                host.update_reward_state(reward_data)
        except Exception:
            pass

    if watch:
        def on_update(state: GameState):
            host.update_state(state)

        def on_error(msg: str):
            print(f"[BoberInSpire] Watch error: {msg}")

        def on_reward_update(data: dict):
            host.update_reward_state(data)

        watcher = GameStateWatcher(path, on_update=on_update, on_error=on_error)
        watcher.start()
        reward_watcher = RewardStateWatcher(reward_path, on_update=on_reward_update)
        reward_watcher.start()
        host.start_continuous_reward_polling()

    print("[BoberInSpire] Overlay bridge ready.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        shutdown_and_exit()


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
