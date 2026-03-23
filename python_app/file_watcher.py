from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .data_parser import load_game_state, load_reward_state
from .models import GameState


class _DebounceGate:
    """Coalesce rapid filesystem events (editor save = modify + sometimes create)."""

    __slots__ = ("_interval_s", "_last")

    def __init__(self, debounce_ms: int) -> None:
        self._last = 0.0
        self._interval_s = debounce_ms / 1000.0

    def try_consume(self) -> bool:
        now = time.time()
        if now - self._last < self._interval_s:
            return False
        self._last = now
        return True


def _event_is_target_file(event: object, target_resolved: Path) -> bool:
    if getattr(event, "is_directory", False):
        return False
    try:
        return Path(getattr(event, "src_path", "")).resolve() == target_resolved
    except OSError:
        return False


class _RewardFileHandler(FileSystemEventHandler):
    """Watches reward state JSON and fires callback on change."""

    def __init__(
        self,
        target_path: Path,
        on_update: Callable[[dict], None],
        debounce_ms: int = 200,
    ):
        super().__init__()
        self._target = target_path.resolve()
        self._on_update = on_update
        self._debounce = _DebounceGate(debounce_ms)

    def _handle_file_change(self, event: object) -> None:
        if not _event_is_target_file(event, self._target):
            return
        if not self._debounce.try_consume():
            return
        try:
            data = load_reward_state(self._target)
            self._on_update(data)
        except Exception:
            pass

    def on_modified(self, event):
        self._handle_file_change(event)

    def on_created(self, event):
        self._handle_file_change(event)


class RewardStateWatcher:
    """Watches bober_reward_state.json for card reward screen updates."""

    def __init__(self, watch_path: str | Path, on_update: Callable[[dict], None]):
        self._path = Path(watch_path).resolve()
        self._on_update = on_update
        self._observer: Observer | None = None

    def start(self):
        handler = _RewardFileHandler(self._path, on_update=self._on_update)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._path.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        if self._path.exists():
            try:
                data = load_reward_state(self._path)
                self._on_update(data)
            except Exception:
                pass

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None


class _StateFileHandler(FileSystemEventHandler):
    """Watches a single JSON file and fires a callback on change."""

    def __init__(
        self,
        target_path: Path,
        on_update: Callable[[GameState], None],
        on_error: Callable[[str], None] | None = None,
        debounce_ms: int = 200,
    ):
        super().__init__()
        self._target = target_path.resolve()
        self._on_update = on_update
        self._on_error = on_error
        self._debounce = _DebounceGate(debounce_ms)

    def on_modified(self, event):
        if not _event_is_target_file(event, self._target):
            return
        if not self._debounce.try_consume():
            return

        try:
            state = load_game_state(self._target)
            self._on_update(state)
        except Exception as exc:
            if self._on_error:
                self._on_error(str(exc))


class GameStateWatcher:
    """Watches combat_state.json for changes and delivers GameState updates."""

    def __init__(
        self,
        watch_path: str | Path,
        on_update: Callable[[GameState], None],
        on_error: Callable[[str], None] | None = None,
    ):
        self._path = Path(watch_path).resolve()
        self._on_update = on_update
        self._on_error = on_error
        self._observer: Observer | None = None

    def start(self):
        handler = _StateFileHandler(
            self._path,
            on_update=self._on_update,
            on_error=self._on_error,
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(self._path.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()

        if self._path.exists():
            try:
                state = load_game_state(self._path)
                self._on_update(state)
            except Exception as exc:
                if self._on_error:
                    self._on_error(str(exc))

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
