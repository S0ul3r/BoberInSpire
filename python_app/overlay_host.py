"""
WebSocket host for the Tauri/React overlay: pushes view-model JSON and accepts settings updates.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from websockets.asyncio.server import ServerConnection, serve

from .data_parser import load_reward_state
from .models import GameState
from .overlay_settings import OverlaySettings, load_settings, save_settings
from .overlay_view_model import build_overlay_view_model
from .reward_advisor import RewardRecommendation


DEFAULT_WS_HOST = "127.0.0.1"
DEFAULT_WS_PORT = 18765
PERF_LOG_INTERVAL_S = 5.0
DEBOUNCE_S = 0.05


class OverlayHost:
    """
    Runs an asyncio WebSocket server on a background thread.
    Call notify_update() from the main thread when game state or reward data changes.
    """

    def __init__(
        self,
        *,
        host: str = DEFAULT_WS_HOST,
        port: int = DEFAULT_WS_PORT,
        debug: bool = False,
    ):
        self.host = host
        self.port = port
        self.debug = debug
        self._settings = load_settings()
        self._last_state: GameState | None = None
        self._last_reward_data: dict | None = None
        self._reward_file_path = ""
        self._reward_file_sig: tuple[int, int] | None = None
        self._reward_cache_sig: str | None = None
        self._reward_cache_rec: RewardRecommendation | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._clients: set[ServerConnection] = set()
        self._debounce_handle: asyncio.TimerHandle | None = None
        self._last_payload_sig: str | None = None
        self._poll_task: asyncio.Task[None] | None = None

        self._perf_render_count = 0
        self._perf_render_ms_total = 0.0
        self._perf_reward_rec_count = 0
        self._perf_reward_rec_ms_total = 0.0
        self._perf_last_log_ts = time.time()

        self._on_shutdown: Callable[[], None] | None = None

    def set_reward_file_path(self, path: str) -> None:
        self._reward_file_path = path

    def set_on_shutdown(self, cb: Callable[[], None] | None) -> None:
        self._on_shutdown = cb

    def update_state(self, state: GameState) -> None:
        self._last_state = state
        if state.enemies:
            rd = self._last_reward_data or {}
            if rd.get("type") != "merchant_cards":
                self._last_reward_data = None
        else:
            self._refresh_reward_if_needed()
        self.notify_update()

    def update_reward_state(self, reward_data: dict) -> None:
        if reward_data and reward_data.get("options"):
            self._last_reward_data = reward_data
        else:
            self._last_reward_data = None
        self.notify_update()

    def _refresh_reward_if_needed(self) -> None:
        if not self._reward_file_path or not self._settings.show_card_reward:
            return
        try:
            p = Path(self._reward_file_path)
            if p.exists():
                stat = p.stat()
                sig = (stat.st_mtime_ns, stat.st_size)
                if sig != self._reward_file_sig:
                    self._reward_file_sig = sig
                    data = load_reward_state(self._reward_file_path)
                    if data and data.get("options"):
                        self._last_reward_data = data
        except OSError:
            pass

    def start_continuous_reward_polling(self) -> None:
        """Reward file is polled from the asyncio loop (started with the WS server)."""
        pass

    async def _poll_reward_loop(self) -> None:
        while self._loop and self._loop.is_running():
            await asyncio.sleep(2.0)
            if not self._reward_file_path:
                continue
            if not self._settings.show_card_reward:
                continue
            changed = False
            try:
                p = Path(self._reward_file_path)
                if p.exists():
                    stat = p.stat()
                    sig = (stat.st_mtime_ns, stat.st_size)
                    if sig != self._reward_file_sig:
                        self._reward_file_sig = sig
                        data = load_reward_state(p)
                        if data and data.get("options"):
                            self._last_reward_data = data
                        else:
                            self._last_reward_data = None
                        changed = True
                else:
                    if self._last_reward_data is not None:
                        self._last_reward_data = None
                        changed = True
                if changed:
                    self.notify_update()
            except OSError:
                pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="OverlayWS", daemon=True)
        self._thread.start()
        deadline = time.time() + 5.0
        while self._loop is None and time.time() < deadline:
            time.sleep(0.02)
        if self._loop is None:
            raise RuntimeError("Overlay WebSocket loop failed to start")

    def notify_update(self) -> None:
        loop = self._loop
        if not loop:
            return
        loop.call_soon_threadsafe(self._schedule_broadcast)

    def _schedule_broadcast(self) -> None:
        if not self._loop:
            return
        if self._debounce_handle:
            self._debounce_handle.cancel()
            self._debounce_handle = None
        self._debounce_handle = self._loop.call_later(DEBOUNCE_S, self._do_broadcast)

    def _do_broadcast(self) -> None:
        self._debounce_handle = None
        asyncio.create_task(self._broadcast_payload())

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def runner():
            async def handler(websocket: ServerConnection):
                self._clients.add(websocket)
                self._schedule_broadcast()
                try:
                    async for message in websocket:
                        await self._handle_client_message(message)
                finally:
                    self._clients.discard(websocket)

            server = await serve(handler, self.host, self.port)
            self._poll_task = asyncio.create_task(self._poll_reward_loop())
            await server.serve_forever()

        try:
            self._loop.run_until_complete(runner())
        finally:
            self._loop.close()

    async def _handle_client_message(self, raw: str) -> None:
        try:
            msg: dict[str, Any] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        mtype = msg.get("type")
        if mtype == "set_settings":
            s = self._settings
            for key in (
                "show_combat_summary",
                "show_enemies",
                "show_strategy",
                "show_relics",
                "show_merchant_relics",
                "show_card_reward",
            ):
                if key in msg:
                    setattr(s, key, bool(msg[key]))
            if "alpha" in msg:
                s.alpha = max(0.35, min(1.0, float(msg["alpha"])))
            save_settings(s)
            self._last_payload_sig = None
            self.notify_update()
        elif mtype == "close_overlay":
            if self._on_shutdown:
                self._on_shutdown()

    async def _broadcast_payload(self) -> None:
        if not self._clients:
            return
        t0 = time.perf_counter()
        payload, new_sig, new_rec, rdc, rdm = build_overlay_view_model(
            self._settings,
            self._last_state,
            self._last_reward_data,
            debug=self.debug,
            reward_file_path=self._reward_file_path,
            reward_cache_sig=self._reward_cache_sig,
            reward_cache_rec=self._reward_cache_rec,
            perf_render_count=self._perf_render_count,
            perf_render_ms_total=self._perf_render_ms_total,
            perf_reward_rec_count=self._perf_reward_rec_count,
            perf_reward_rec_ms_total=self._perf_reward_rec_ms_total,
        )
        self._reward_cache_sig = new_sig
        self._reward_cache_rec = new_rec
        if rdc:
            self._perf_reward_rec_count += rdc
            self._perf_reward_rec_ms_total += rdm

        sig = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        if sig == self._last_payload_sig:
            return
        self._last_payload_sig = sig

        dt_ms = (time.perf_counter() - t0) * 1000.0
        self._perf_render_count += 1
        self._perf_render_ms_total += dt_ms
        self._maybe_log_perf()

        text = json.dumps(payload, ensure_ascii=True)
        dead: list[ServerConnection] = []
        for ws in self._clients:
            try:
                await ws.send(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def _maybe_log_perf(self) -> None:
        now = time.time()
        if now - self._perf_last_log_ts < PERF_LOG_INTERVAL_S:
            return
        self._perf_last_log_ts = now

        def _avg(total: float, count: int) -> float:
            return (total / count) if count > 0 else 0.0

        print(
            "[BoberInSpire][Perf] "
            f"renders={self._perf_render_count} avg_render_ms={_avg(self._perf_render_ms_total, self._perf_render_count):.2f} "
            f"reward_recs={self._perf_reward_rec_count} avg_reward_rec_ms={_avg(self._perf_reward_rec_ms_total, self._perf_reward_rec_count):.2f}"
        )


def resolve_overlay_exe() -> Path | None:
    env = os.environ.get("BOBER_OVERLAY_EXE")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    root = Path(__file__).resolve().parent.parent
    bundled = root / "BoberInSpireOverlay.exe"
    if bundled.is_file():
        return bundled
    for rel in (
        "overlay-ui/src-tauri/target/release/bober-inspire-overlay.exe",
        "overlay-ui/src-tauri/target/debug/bober-inspire-overlay.exe",
    ):
        cand = root / rel
        if cand.is_file():
            return cand
    return None
