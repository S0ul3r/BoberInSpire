from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from .data_parser import load_game_state, ParseError
from .models import GameState


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
        self._last_trigger = 0.0
        self._debounce_s = debounce_ms / 1000.0

    def on_modified(self, event):
        if event.is_directory:
            return

        changed = Path(event.src_path).resolve()
        if changed != self._target:
            return

        now = time.time()
        if now - self._last_trigger < self._debounce_s:
            return
        self._last_trigger = now

        try:
            state = load_game_state(self._target)
            self._on_update(state)
        except (ParseError, FileNotFoundError, Exception) as exc:
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
