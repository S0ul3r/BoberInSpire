from __future__ import annotations

import json
import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable
from pathlib import Path
import time

from .utils import strip_bbcode

from .combat_engine import (
    IncomingDamageResult,
    calculate_incoming_damage,
    summarize_hand,
)
from .strategy import compute_strategy
from .models import GameState, MerchantRelic, Relic
from .data_parser import load_reward_state
from .reward_advisor import recommend
from .overlay_settings import OverlaySettings, load_settings, save_settings
from .relic_db import (
    get_short_description_only,
    rarity_color,
    rarity_sort_key,
)


BG_COLOR = "#12121f"
FG_COLOR = "#e0e0e0"
ACCENT_COLOR = "#e94560"
LETHAL_COLOR = "#00ff88"
CARD_COLOR = "#1c1c30"
HEADER_COLOR = "#0f3460"
ENERGY_COLOR = "#f5a623"
SAFE_COLOR = "#00e676"
DANGER_COLOR = "#ff4444"
WARN_COLOR = "#ffaa00"
BLOCK_COLOR = "#4da6ff"
RELIC_BG = "#181828"
SUMMARY_BG = "#161626"
NET_SAFE_BG = "#0a2e18"
NET_WARN_BG = "#2e1a00"
NET_DANGER_BG = "#2e0808"
ENEMY_SECTION_BG = "#280a0a"
WINDOW_WIDTH = 460
WINDOW_HEIGHT = 720
MIN_WIDTH = 320
MAX_WIDTH = 900
MIN_HEIGHT = 400
MAX_HEIGHT = 1200
RESIZE_GRIP_SIZE = 14
WARN_HP_THRESHOLD = 0.3

# Card reward / merchant advisor — higher contrast than main combat cards
REWARD_BANNER_BG = "#142a55"
REWARD_SUBHEADER_BG = "#1a3366"
REWARD_ROW_BG = "#262a3d"
REWARD_REASON_BG = "#1c2233"
REWARD_REASON_FG = "#dde6f2"
REWARD_TIER_S = "#4dff9e"
REWARD_TIER_A = "#ffcc4d"
REWARD_TIER_B = "#7ec8ff"
REWARD_TIER_C = "#f4d080"
REWARD_TIER_D = "#ff9aab"
REWARD_TIER_LOW = "#aab8ce"
REWARD_WIKI_HINT_FG = "#b8f2c0"
REWARD_WIKI_HINT_BG = "#15221a"

PERF_LOG_INTERVAL_S = 5.0


class CombatOverlay:
    """Semi-transparent always-on-top overlay showing combat calculations."""

    def __init__(self, on_close: Callable[[], None] | None = None, debug: bool = False):
        self.root = tk.Tk()
        self.root.title("BoberInSpire")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self._settings: OverlaySettings = load_settings()
        self._apply_alpha(self._settings.alpha)
        self.root.configure(bg=BG_COLOR)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+50+50")

        self._drag_data: dict = {"x": 0, "y": 0}
        self._resize_data: dict | None = None
        self._on_close = on_close
        self._debug = debug
        self._settings_win: tk.Toplevel | None = None
        self._last_state: GameState | None = None
        self._last_reward_data: dict | None = None
        self._reward_file_path: str = ""
        self._reward_poll_timer: str | None = None
        self._reward_file_sig: tuple[int, int] | None = None
        self._render_scheduled = False
        self._last_render_sig: str | None = None
        self._last_reward_sig: str | None = None
        self._last_reward_rec = None
        self._perf_last_log_ts = time.time()
        self._perf_render_count = 0
        self._perf_render_ms_total = 0.0
        self._perf_reward_rec_count = 0
        self._perf_reward_rec_ms_total = 0.0

        self._build_fonts()
        self._build_widgets()

    def _build_fonts(self):
        self.font_title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.font_header = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.font_net = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.font_body = tkfont.Font(family="Consolas", size=10)
        self.font_body_bold = tkfont.Font(family="Consolas", size=10, weight="bold")
        self.font_small = tkfont.Font(family="Consolas", size=9)
        self.font_summary = tkfont.Font(family="Segoe UI", size=9, slant="italic")
        self.font_btn = tkfont.Font(family="Segoe UI", size=9)

    def _build_widgets(self):
        content = tk.Frame(self.root, bg=BG_COLOR)
        content.pack(side="left", fill="both", expand=True)

        title_bar = tk.Frame(content, bg="#0d0d1a", cursor="fleur")
        title_bar.pack(fill="x")

        title_bar.bind("<ButtonPress-1>", self._start_drag)
        title_bar.bind("<B1-Motion>", self._on_drag)

        tk.Label(
            title_bar, text="\u2694 COMBAT ASSISTANT",
            font=self.font_title, fg=ACCENT_COLOR, bg="#0d0d1a",
            anchor="w", padx=8, pady=4,
        ).pack(side="left")

        close_btn = tk.Label(
            title_bar, text=" \u2715 ", font=self.font_btn,
            fg="#ff5555", bg="#0d0d1a", cursor="hand2",
        )
        close_btn.pack(side="right", padx=(0, 4))
        close_btn.bind("<Button-1>", lambda e: self._handle_close())

        settings_btn = tk.Label(
            title_bar, text=" \u2699 ", font=self.font_btn,
            fg="#aaa", bg="#0d0d1a", cursor="hand2",
        )
        settings_btn.pack(side="right")
        settings_btn.bind("<Button-1>", lambda e: self._open_settings())

        self.info_frame = tk.Frame(content, bg=BG_COLOR)
        self.info_frame.pack(fill="x", padx=8)

        canvas_frame = tk.Frame(content, bg=BG_COLOR)
        canvas_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self.canvas = tk.Canvas(canvas_frame, bg=BG_COLOR, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg=BG_COLOR)

        def _on_scroll_configure(_e):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self._update_scrollbar_visibility()

        def _on_yscroll(first, last):
            self._scrollbar.set(first, last)
            self._update_scrollbar_visibility()

        self.scroll_frame.bind("<Configure>", _on_scroll_configure)
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=_on_yscroll)

        self.canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar is shown only when content overflows (see _update_scrollbar_visibility)
        self._scrollbar_visible = False

        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        self.status_label = tk.Label(
            content,
            text="Waiting for game state...  (\u2699 = settings)",
            font=self.font_small,
            fg="#888",
            bg=BG_COLOR,
            anchor="w",
            padx=12,
            pady=4,
        )
        self.status_label.pack(fill="x", side="bottom")

        grip_container = tk.Frame(self.root, width=RESIZE_GRIP_SIZE, bg="#0d0d1a")
        grip_container.pack(side="right", fill="y")
        grip_container.pack_propagate(False)
        # "size_nwse" is X11-only; on Windows use "sizing" for resize cursor
        resize_cursor = "size_nwse" if platform.system() != "Windows" else "sizing"
        resize_grip = tk.Frame(
            grip_container,
            width=RESIZE_GRIP_SIZE,
            height=RESIZE_GRIP_SIZE,
            bg="#1a1a2e",
            cursor=resize_cursor,
        )
        resize_grip.pack(side="bottom")
        resize_grip.pack_propagate(False)
        resize_grip.bind("<ButtonPress-1>", self._start_resize)
        resize_grip.bind("<B1-Motion>", self._on_resize)
        resize_grip.bind("<ButtonRelease-1>", self._end_resize)
        self._resize_grip = resize_grip

    def _start_resize(self, event):
        self._resize_data = {
            "x_root": event.x_root,
            "y_root": event.y_root,
            "width": self.root.winfo_width(),
            "height": self.root.winfo_height(),
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
        }
        self.root.bind("<B1-Motion>", self._on_resize)
        self.root.bind("<ButtonRelease-1>", self._end_resize)

    def _on_resize(self, event):
        if not self._resize_data:
            return
        r = self._resize_data
        dx = event.x_root - r["x_root"]
        dy = event.y_root - r["y_root"]
        w = max(MIN_WIDTH, min(MAX_WIDTH, r["width"] + dx))
        h = max(MIN_HEIGHT, min(MAX_HEIGHT, r["height"] + dy))
        self.root.geometry(f"{int(w)}x{int(h)}+{r['x']}+{r['y']}")

    def _end_resize(self, event=None):
        self._resize_data = None
        self.root.unbind("<B1-Motion>")
        self.root.unbind("<ButtonRelease-1>")

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _apply_alpha(self, alpha: float) -> None:
        a = max(0.35, min(1.0, float(alpha)))
        self.root.attributes("-alpha", a)

    def _open_settings(self):
        if self._settings_win is not None:
            try:
                self._settings_win.lift()
                self._settings_win.focus_force()
            except tk.TclError:
                self._settings_win = None
            else:
                return

        win = tk.Toplevel(self.root)
        win.title("BoberInSpire — Settings")
        win.configure(bg="#1a1a2e")
        win.transient(self.root)
        win.resizable(False, False)
        self._settings_win = win

        pad = {"padx": 12, "pady": 6}
        tk.Label(
            win, text="Visible panels", font=self.font_header,
            fg=FG_COLOR, bg="#1a1a2e", anchor="w",
        ).pack(fill="x", **pad)

        vars_map: dict[str, tk.BooleanVar] = {}

        def row(label: str, key: str):
            v = tk.BooleanVar(value=getattr(self._settings, key))
            vars_map[key] = v
            tk.Checkbutton(
                win, text=label, variable=v, font=self.font_body,
                fg=FG_COLOR, bg="#1a1a2e", selectcolor="#2a2a4a",
                activebackground="#1a1a2e", activeforeground=FG_COLOR,
                anchor="w",
            ).pack(fill="x", padx=12, pady=2)

        row("Combat summary (HP / energy / net damage & block)", "show_combat_summary")
        row("Enemies (intents, per-enemy line)", "show_enemies")
        row("Strategy (hand summary, suggested play)", "show_strategy")
        row("Relics (combat)", "show_relics")
        row("Merchant relics (shop)", "show_merchant_relics")
        row("Card reward advisor (pick / merchant cards)", "show_card_reward")

        tk.Label(
            win, text="Transparency", font=self.font_header,
            fg=FG_COLOR, bg="#1a1a2e", anchor="w",
        ).pack(fill="x", **pad)

        alpha_var = tk.DoubleVar(value=self._settings.alpha)
        scale = tk.Scale(
            win, from_=0.35, to=1.0, resolution=0.05, orient="horizontal",
            variable=alpha_var, font=self.font_small,
            fg=FG_COLOR, bg="#1a1a2e", highlightthickness=0,
            command=lambda _: self._apply_alpha(alpha_var.get()),
        )
        scale.pack(fill="x", padx=12, pady=(0, 8))

        btn_row = tk.Frame(win, bg="#1a1a2e")
        btn_row.pack(fill="x", pady=(4, 12))

        def apply_save():
            for key, var in vars_map.items():
                setattr(self._settings, key, var.get())
            self._settings.alpha = max(0.35, min(1.0, alpha_var.get()))
            save_settings(self._settings)
            self._last_render_sig = None
            self._request_render()

        def save_and_close():
            apply_save()
            self._settings_win = None
            win.destroy()

        tk.Button(
            btn_row, text="Save & apply", command=save_and_close,
            font=self.font_btn, bg="#2a4a6a", fg=FG_COLOR,
        ).pack(side="right", padx=12)

        def cancel_close():
            self._apply_alpha(self._settings.alpha)
            self._settings_win = None
            win.destroy()

        tk.Button(
            btn_row, text="Cancel", command=cancel_close,
            font=self.font_btn, bg="#333", fg="#ccc",
        ).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", cancel_close)

    def _handle_close(self):
        if self._on_close:
            self._on_close()
        self.root.destroy()

    def _clear_scroll_frame(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        for w in self.info_frame.winfo_children():
            w.destroy()

    def _update_scrollbar_visibility(self):
        """Show scrollbar only when content overflows the canvas."""
        self.canvas.update_idletasks()
        try:
            first, last = self.canvas.yview()
            need_scrollbar = (last - first) < 0.999
        except Exception:
            need_scrollbar = False
        if need_scrollbar and not self._scrollbar_visible:
            self._scrollbar.pack(side="right", fill="y")
            self._scrollbar_visible = True
        elif not need_scrollbar and self._scrollbar_visible:
            self._scrollbar.pack_forget()
            self._scrollbar_visible = False

    def set_reward_file_path(self, path: str):
        """Set path for reward state JSON (used when checking reward on combat update)."""
        self._reward_file_path = path

    def start_continuous_reward_polling(self):
        """Start polling reward file every 2 seconds (call when in watch mode)."""
        if self._reward_poll_timer or not self._reward_file_path:
            return
        self._poll_reward_file_continuous()

    def _poll_reward_file_continuous(self):
        """Poll reward file every 2 seconds regardless of combat state."""
        if not self._reward_file_path:
            return
        if not self._settings.show_card_reward:
            self._reward_poll_timer = self.root.after(2000, self._poll_reward_file_continuous)
            return
        changed = False
        try:
            from pathlib import Path
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
                self._request_render()
        except Exception:
            pass
        self._reward_poll_timer = self.root.after(2000, self._poll_reward_file_continuous)

    def _stop_reward_polling(self):
        """Cancel reward file polling."""
        if self._reward_poll_timer:
            try:
                self.root.after_cancel(self._reward_poll_timer)
            except tk.TclError:
                pass
            self._reward_poll_timer = None

    def update_state(self, state: GameState):
        """Refresh the overlay with a new GameState."""
        self._last_state = state
        if state.enemies:
            rd = self._last_reward_data or {}
            if rd.get("type") != "merchant_cards":
                self._last_reward_data = None
        else:
            self._refresh_reward_if_needed()
        self._request_render()

    def update_reward_state(self, reward_data: dict):
        """Update overlay with reward screen data (from RewardStateWatcher)."""
        if reward_data and reward_data.get("options"):
            self._last_reward_data = reward_data
        else:
            self._last_reward_data = None
        self._request_render()

    def _refresh_reward_if_needed(self):
        """When combat state updates, also check reward file (mod may write both)."""
        if not self._reward_file_path or not self._settings.show_card_reward:
            return
        try:
            from pathlib import Path
            p = Path(self._reward_file_path)
            if p.exists():
                stat = p.stat()
                sig = (stat.st_mtime_ns, stat.st_size)
                if sig != self._reward_file_sig:
                    self._reward_file_sig = sig
                    data = load_reward_state(self._reward_file_path)
                    if data and data.get("options"):
                        self._last_reward_data = data
        except Exception:
            pass

    def _request_render(self):
        if self._render_scheduled:
            return
        self._render_scheduled = True
        self.root.after(50, self._run_scheduled_render)

    def _run_scheduled_render(self):
        self._render_scheduled = False
        self._render_all()

    def _any_panel_enabled(self, show_pick: bool) -> bool:
        s = self._settings
        return any(
            (
                s.show_combat_summary,
                s.show_enemies,
                s.show_strategy,
                s.show_relics,
                s.show_merchant_relics,
                s.show_card_reward and show_pick,
            )
        )

    def _should_show_card_reward(self) -> bool:
        """Post-combat pick or merchant shop cards: have options; hide during real combat only."""
        if not self._settings.show_card_reward:
            return False
        if not self._last_reward_data or not self._last_reward_data.get("options"):
            return False
        screen_type = self._last_reward_data.get("type", "card_reward")
        # Map merchant can still carry a stale combat snapshot with enemies; trust exported shop list.
        if screen_type == "merchant_cards":
            return True
        if self._last_state and self._last_state.enemies:
            return False
        return True

    def _render_all(self):
        """Re-render overlay from stored state and reward data."""
        render_sig = self._compute_render_sig()
        if render_sig == self._last_render_sig:
            return
        self._last_render_sig = render_sig
        t0 = time.perf_counter()
        self._clear_scroll_frame()
        state = self._last_state
        show_pick = self._should_show_card_reward()
        s = self._settings

        if show_pick:
            self._render_card_reward()

        incoming: IncomingDamageResult | None = None
        if state and state.enemies and (s.show_combat_summary or s.show_enemies):
            incoming = calculate_incoming_damage(state)

        if state and s.show_combat_summary:
            self._render_player_info(state, incoming)

        if state and not show_pick:
            if s.show_enemies:
                self._render_enemies(state, incoming)
            if s.show_strategy:
                self._render_strategy(state)

        if state and s.show_relics:
            self._render_relics(state)

        at_merchant_cards = (
            show_pick
            and (self._last_reward_data or {}).get("type") == "merchant_cards"
        )
        if (
            state
            and state.merchant_relics
            and s.show_merchant_relics
            and (not show_pick or at_merchant_cards)
        ):
            self._render_merchant_relics(state.merchant_relics)

        if self._debug:
            self._render_debug()

        if show_pick:
            if (self._last_reward_data or {}).get("type") == "merchant_cards":
                self.status_label.config(text="Merchant cards  |  Card advisor")
            else:
                self.status_label.config(text="Choose a Card  |  Card advisor")
        elif state:
            if not self._any_panel_enabled(False):
                self.status_label.config(text="All panels off — open \u2699 settings")
            else:
                self.status_label.config(text=f"Turn {state.turn}  |  Updated")
        else:
            self.status_label.config(text="Waiting for game state...  (\u2699 = settings)")
        self.root.after(50, self._update_scrollbar_visibility)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self._perf_render_count += 1
        self._perf_render_ms_total += dt_ms
        self._maybe_log_perf()

    def _compute_render_sig(self) -> str:
        state = self._last_state
        reward = self._last_reward_data
        state_sig = None
        if state:
            try:
                state_sig = (
                    state.turn,
                    state.player.hp,
                    state.player.block,
                    state.player.energy,
                    len(state.hand),
                    tuple((e.name, e.hp, e.block, e.intent_damage, e.intent_hits) for e in state.enemies),
                )
            except Exception:
                state_sig = str(state)
        reward_sig = None
        if reward:
            reward_sig = (
                reward.get("type"),
                reward.get("character"),
                tuple(reward.get("options") or []),
                len(reward.get("deck") or []),
                len(reward.get("relics") or []),
            )
        st = self._settings
        settings_sig = (
            st.show_combat_summary,
            st.show_enemies,
            st.show_strategy,
            st.show_relics,
            st.show_merchant_relics,
            st.show_card_reward,
            round(st.alpha, 2),
        )
        return f"{state_sig}|{reward_sig}|{self._debug}|{settings_sig}"

    def _render_debug(self):
        p = Path(self._reward_file_path) if self._reward_file_path else None
        exists = bool(p and p.exists())
        mtime = ""
        size = ""
        if exists and p:
            try:
                stat = p.stat()
                mtime = time.strftime("%H:%M:%S", time.localtime(stat.st_mtime))
                size = f"{stat.st_size}B"
            except Exception:
                pass

        rd = self._last_reward_data or {}
        opts = rd.get("options") or []
        opts_preview = ", ".join(str(x) for x in opts[:3])
        if len(opts) > 3:
            opts_preview += f", …(+{len(opts)-3})"

        deck = rd.get("deck") or []
        deck_uniq = len({str(c).lower() for c in deck})
        deck_preview = ", ".join(str(x) for x in deck[:6])
        if len(deck) > 6:
            deck_preview += f", …(+{len(deck)-6})"

        lines = [
            f"Reward file: {self._reward_file_path or '(not set)'}",
            f"Exists: {exists}  MTime: {mtime or '-'}  Size: {size or '-'}",
            f"Parsed options: {len(opts)}  [{opts_preview}]",
            f"Reward deck: {len(deck)} cards, {deck_uniq} unique  [{deck_preview}]",
            f"Reward character: {rd.get('character', '-')!r}  type: {rd.get('type', '-')!r}",
            f"Perf renders: {self._perf_render_count} avg_ms={self._avg(self._perf_render_ms_total, self._perf_render_count):.2f}",
            f"Perf reward recommend: {self._perf_reward_rec_count} avg_ms={self._avg(self._perf_reward_rec_ms_total, self._perf_reward_rec_count):.2f}",
        ]

        panel = tk.Frame(self.info_frame, bg="#0d0d1a")
        panel.pack(fill="x", pady=(6, 0))
        tk.Label(
            panel, text="DEBUG", font=self.font_header,
            fg=WARN_COLOR, bg="#0d0d1a", anchor="w", padx=6, pady=2,
        ).pack(fill="x")
        tk.Label(
            panel, text="\n".join(lines), font=self.font_small,
            fg=FG_COLOR, bg="#0d0d1a", anchor="w", justify="left", padx=6, pady=4,
        ).pack(fill="x")

    @staticmethod
    def _avg(total: float, count: int) -> float:
        return (total / count) if count > 0 else 0.0

    def _maybe_log_perf(self):
        now = time.time()
        if now - self._perf_last_log_ts < PERF_LOG_INTERVAL_S:
            return
        self._perf_last_log_ts = now
        print(
            "[BoberInSpire][Perf] "
            f"renders={self._perf_render_count} avg_render_ms={self._avg(self._perf_render_ms_total, self._perf_render_count):.2f} "
            f"reward_recs={self._perf_reward_rec_count} avg_reward_rec_ms={self._avg(self._perf_reward_rec_ms_total, self._perf_reward_rec_count):.2f}"
        )

    # ── Player info + NET damage banner ─────────────────────────

    def _render_player_info(self, state: GameState, incoming: IncomingDamageResult | None = None):
        p = state.player
        if incoming is None and state.enemies:
            incoming = calculate_incoming_damage(state)

        # Compact one-line stats row
        parts = [f"HP: {p.hp}/{p.max_hp}", f"Energy: {p.energy}/{p.max_energy}"]
        str_text = f"STR: {p.strength:+d}" if p.strength != 0 else "STR: 0"
        dex_text = f"DEX: {p.dexterity:+d}" if p.dexterity != 0 else "DEX: 0"
        parts += [str_text, dex_text]
        if p.block > 0:
            parts.append(f"\u26e8 {p.block}")

        tk.Label(
            self.info_frame, text="  ".join(parts), font=self.font_body,
            fg=ENERGY_COLOR, bg=BG_COLOR, anchor="w", padx=6, pady=2,
        ).pack(fill="x")

        # Prominent NET damage banner — always visible when enemies present
        if state.enemies and incoming is not None and incoming.total_incoming > 0:
            if incoming.expected_hp == 0:
                net_text = f"  \u2620  LETHAL!  {incoming.net_damage} dmg  \u2192  HP: 0"
                net_bg, net_fg = NET_DANGER_BG, DANGER_COLOR
            elif incoming.net_damage == 0:
                net_text = f"  \u2714  SAFE  \u2014  block covers all {incoming.total_incoming} dmg"
                net_bg, net_fg = NET_SAFE_BG, SAFE_COLOR
            elif incoming.net_damage < p.hp * WARN_HP_THRESHOLD:
                net_text = f"  \u25bc  {incoming.net_damage} dmg incoming  \u2192  HP: {incoming.expected_hp}"
                net_bg, net_fg = NET_WARN_BG, WARN_COLOR
            else:
                net_text = f"  \u25bc  {incoming.net_damage} dmg incoming  \u2192  HP: {incoming.expected_hp}"
                net_bg, net_fg = NET_DANGER_BG, DANGER_COLOR
        elif state.enemies and incoming is not None:
            net_text = "  \u2714  No attack incoming this turn"
            net_bg, net_fg = NET_SAFE_BG, SAFE_COLOR
        else:
            return

        net_panel = tk.Frame(self.info_frame, bg=net_bg)
        net_panel.pack(fill="x", pady=(2, 0))
        tk.Label(
            net_panel, text=net_text, font=self.font_net,
            fg=net_fg, bg=net_bg, anchor="w", padx=8, pady=5,
        ).pack(fill="x")

    # ── Enemies section ──────────────────────────────────────────

    def _render_enemies(self, state: GameState, incoming: IncomingDamageResult | None = None):
        if not state.enemies:
            return
        if incoming is None:
            incoming = calculate_incoming_damage(state)

        tk.Label(
            self.scroll_frame, text=f"ENEMIES ({len(state.enemies)})",
            font=self.font_header, fg=FG_COLOR, bg=ENEMY_SECTION_BG,
            anchor="w", padx=8, pady=3,
        ).pack(fill="x", pady=(4, 1))

        for ei, enemy in zip(incoming.per_enemy, state.enemies):
            # Build debuff/buff badges
            badges = ""
            if enemy.weak_turns > 0:
                badges += " [Weak]"
            if enemy.vulnerable_turns > 0:
                badges += " [Vuln]"
            if enemy.strength != 0:
                badges += f" [STR{enemy.strength:+d}]"

            # Build intent display
            if ei.total_damage > 0:
                if ei.intended_hits > 1:
                    per_hit = ei.intended_damage // max(ei.intended_hits, 1)
                    dmg_str = f"{per_hit}x{ei.intended_hits} ({ei.total_damage})"
                else:
                    dmg_str = f"{ei.total_damage}"
                intent_str = f"\u2694 {dmg_str} dmg"
                intent_color = DANGER_COLOR
            else:
                intent_str = f"\u2022 {ei.move_type.replace('Intent', '')}"
                intent_color = "#888"

            hp_str = f"HP {enemy.hp}/{enemy.max_hp}"
            line = f"  {ei.name:<16s}  {intent_str:<18s}  {hp_str}{badges}"

            tk.Label(
                self.scroll_frame, text=line, font=self.font_body,
                fg=intent_color, bg=BG_COLOR, anchor="w", padx=6, pady=2,
            ).pack(fill="x")

        # Block line (compact, only if player has block)
        if incoming.player_block > 0:
            tk.Label(
                self.scroll_frame,
                text=f"  \u26e8 Your block: {incoming.player_block}  \u2014  absorbs {min(incoming.player_block, incoming.total_incoming)} of {incoming.total_incoming} dmg",
                font=self.font_small, fg=BLOCK_COLOR, bg=BG_COLOR,
                anchor="w", padx=8, pady=1,
            ).pack(fill="x")

    # ── Strategy ──────────────────────────────────────────────────

    def _render_strategy(self, state: GameState):
        if not state.hand or not state.enemies:
            return

        strat = compute_strategy(state)
        hs = summarize_hand(state)

        tk.Label(
            self.scroll_frame, text="STRATEGY", font=self.font_header,
            fg="#fff", bg="#142810", anchor="w", padx=8, pady=3,
        ).pack(fill="x", pady=(8, 1))

        # Hand summary (ATK/BLK) at top of strategy
        atk_line = (
            f"  \u2694 ATK: {hs.attack_count}  |  max {hs.max_playable_damage} dmg  "
            f"(pot. {hs.total_potential_damage}, {hs.total_attack_energy}E)"
        )
        blk_line = (
            f"  \u26E8 BLK: {hs.block_count}  |  max {hs.max_playable_block} blk  "
            f"(pot. {hs.total_potential_block}, {hs.total_block_energy}E)"
        )
        tk.Label(
            self.scroll_frame, text=atk_line, font=self.font_body,
            fg=ACCENT_COLOR, bg=BG_COLOR, anchor="w", padx=10, pady=1,
        ).pack(fill="x")
        tk.Label(
            self.scroll_frame, text=blk_line, font=self.font_body,
            fg=BLOCK_COLOR, bg=BG_COLOR, anchor="w", padx=10, pady=1,
        ).pack(fill="x")
        if hs.other_count > 0:
            tk.Label(
                self.scroll_frame, text=f"  \u2726 Other: {hs.other_count} cards",
                font=self.font_body, fg="#aaa", bg=BG_COLOR, anchor="w", padx=10, pady=1,
            ).pack(fill="x")
        tk.Frame(self.scroll_frame, bg="#333", height=1).pack(fill="x", padx=10, pady=3)

        if strat.is_safe:
            safety = f"  \u2714 SAFE  (block surplus: +{strat.block_surplus})"
            safety_color = SAFE_COLOR
        elif strat.prioritize_kill and strat.any_lethal:
            safety = "  \u2694 KILL POSSIBLE  \u2014 attack first, then block if needed"
            safety_color = LETHAL_COLOR
        elif strat.block_needed > 0 and strat.total_block_gain < strat.block_needed:
            deficit = strat.block_needed - strat.total_block_gain
            safety = f"  \u26A0 DANGER  (need {deficit} more block!)"
            safety_color = DANGER_COLOR
        else:
            net = strat.incoming_damage - strat.current_block - strat.total_block_gain
            safety = f"  \u26A0 TAKING {max(net, 0)} dmg"
            safety_color = WARN_COLOR

        tk.Label(
            self.scroll_frame, text=safety, font=self.font_body,
            fg=safety_color, bg=BG_COLOR, anchor="w", padx=10, pady=2,
        ).pack(fill="x")

        if strat.any_lethal:
            kills = ", ".join(strat.any_lethal)
            tk.Label(
                self.scroll_frame,
                text=f"  \u2620 Can KILL: {kills}",
                font=self.font_body, fg=LETHAL_COLOR, bg=BG_COLOR,
                anchor="w", padx=10, pady=1,
            ).pack(fill="x")

        tk.Frame(self.scroll_frame, bg="#333", height=1).pack(fill="x", padx=10, pady=3)

        tk.Label(
            self.scroll_frame, text="  Suggested play:", font=self.font_body,
            fg="#ccc", bg=BG_COLOR, anchor="w", padx=10, pady=1,
        ).pack(fill="x")

        for i, cs in enumerate(strat.suggested_cards, 1):
            if cs.role == "block":
                icon = "\u26E8"
                val = f"+{cs.value} blk"
                color = BLOCK_COLOR
            elif cs.role == "add_attack":
                icon = "\u2694"
                val = "random atk (play first)"
                color = LETHAL_COLOR
            else:
                icon = "\u2694"
                val = f"{cs.value} dmg"
                color = ACCENT_COLOR

            line = f"  {i}. {icon} {cs.name}  [{cs.energy_cost}E]  {val}"
            tk.Label(
                self.scroll_frame, text=line, font=self.font_body,
                fg=color, bg=CARD_COLOR, anchor="w", padx=10, pady=1,
            ).pack(fill="x", padx=4, pady=1)

        tk.Frame(self.scroll_frame, bg="#333", height=1).pack(fill="x", padx=10, pady=3)

        summary = (
            f"  Total: {strat.total_damage} dmg + {strat.total_block_gain} blk  "
            f"| {strat.energy_used}E used, {strat.energy_remaining}E left"
        )
        tk.Label(
            self.scroll_frame, text=summary, font=self.font_body,
            fg=ENERGY_COLOR, bg=BG_COLOR, anchor="w", padx=10, pady=2,
        ).pack(fill="x")

    # ── Card Reward (post-combat pick) ────────────────────────────

    def _render_card_reward(self):
        """Show card reward recommendations when on the Choose a Card screen."""
        if not self._settings.show_card_reward:
            return
        data = self._last_reward_data
        if not data or not data.get("options"):
            return

        screen_type = data.get("type", "card_reward")
        banner = (
            "MERCHANT — CARDS FOR SALE"
            if screen_type == "merchant_cards"
            else "CHOOSE A CARD"
        )
        tk.Label(
            self.scroll_frame,
            text=banner,
            font=self.font_header,
            fg=LETHAL_COLOR,
            bg=REWARD_BANNER_BG,
            anchor="w",
            padx=8,
            pady=4,
        ).pack(fill="x", pady=(0, 2))

        reward_sig = json.dumps(
            {
                "character": data.get("character", "Unknown"),
                "deck": data.get("deck", []),
                "relics": data.get("relics", []),
                "options": data.get("options", []),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        if reward_sig == self._last_reward_sig and self._last_reward_rec is not None:
            rec = self._last_reward_rec
        else:
            t0 = time.perf_counter()
            rec = recommend(
                character=data.get("character", "Unknown"),
                deck=data.get("deck", []),
                relics=data.get("relics", []),
                options=data.get("options", []),
            )
            self._last_reward_sig = reward_sig
            self._last_reward_rec = rec
            self._perf_reward_rec_count += 1
            self._perf_reward_rec_ms_total += (time.perf_counter() - t0) * 1000.0

        tk.Label(
            self.scroll_frame,
            text="CARD REWARD",
            font=self.font_header,
            fg="#ffffff",
            bg=REWARD_SUBHEADER_BG,
            anchor="w",
            padx=8,
            pady=3,
        ).pack(fill="x", pady=(4, 1))

        if getattr(rec, "wiki_build_title", None):
            tk.Label(
                self.scroll_frame,
                text=f"  Deck fit (wiki builds): {rec.wiki_build_title}",
                font=self.font_small,
                fg=REWARD_WIKI_HINT_FG,
                bg=REWARD_WIKI_HINT_BG,
                anchor="w",
                padx=10,
                pady=3,
                wraplength=WINDOW_WIDTH - 24,
                justify="left",
            ).pack(fill="x", padx=2)

        best = rec.best_card
        for r in rec.recommendations:
            is_best = r.name == best
            tier_color = (
                REWARD_TIER_S
                if r.tier == "S"
                else REWARD_TIER_A
                if r.tier == "A"
                else REWARD_TIER_B
                if r.tier == "B"
                else REWARD_TIER_C
                if r.tier == "C"
                else REWARD_TIER_D
                if r.tier == "D"
                else REWARD_TIER_LOW
            )
            prefix = "  \u2714 BEST  " if is_best else f"  {r.tier}  "
            src_tiers: list[str] = []
            if getattr(r, "mobalytics_tier", None):
                src_tiers.append(f"M:{r.mobalytics_tier}")
            if getattr(r, "wiki_tier", None):
                src_tiers.append(f"W:{r.wiki_tier}")
            tier_suffix = f"  [{' '.join(src_tiers)}]" if src_tiers else ""
            line = f"{prefix} {r.name}  (score {r.score}){tier_suffix}"
            tk.Label(
                self.scroll_frame,
                text=line,
                font=self.font_body_bold if is_best else self.font_body,
                fg=tier_color,
                bg=REWARD_ROW_BG,
                anchor="w",
                padx=10,
                pady=3,
            ).pack(fill="x", padx=4, pady=(2, 0))
            detail = (r.reason or "").strip()
            if detail:
                tk.Label(
                    self.scroll_frame,
                    text=f"      \u2022 {detail}",
                    font=self.font_small,
                    fg=REWARD_REASON_FG,
                    bg=REWARD_REASON_BG,
                    anchor="w",
                    padx=12,
                    pady=4,
                    wraplength=WINDOW_WIDTH - 36,
                    justify="left",
                ).pack(fill="x", padx=6, pady=(0, 6))
            else:
                tk.Frame(self.scroll_frame, height=4, bg=BG_COLOR).pack(fill="x")

        if rec.warnings:
            for w in rec.warnings:
                tk.Label(
                    self.scroll_frame, text=f"  \u26A0 {w}",
                    font=self.font_small, fg=WARN_COLOR, bg=BG_COLOR,
                    anchor="w", padx=10, pady=1, wraplength=WINDOW_WIDTH - 30, justify="left",
                ).pack(fill="x")

    # ── Relics ───────────────────────────────────────────────────

    def _render_relics(self, state: GameState):
        if not state.relics:
            return

        sorted_relics = sorted(
            state.relics,
            key=lambda r: rarity_sort_key(r.rarity),
        )

        tk.Label(
            self.scroll_frame, text=f"RELICS ({len(sorted_relics)})",
            font=self.font_header, fg=FG_COLOR, bg="#2a1a3e",
            anchor="w", padx=8, pady=3,
        ).pack(fill="x", pady=(6, 1))

        with_short = []
        without_short = []
        for relic in sorted_relics:
            short = strip_bbcode(get_short_description_only(relic.name))
            if short:
                with_short.append((relic, short))
            else:
                without_short.append(relic)

        for relic, short in with_short:
            color = rarity_color(relic.rarity)
            line = f"  {relic.name}  \u2022 {short}"
            tk.Label(
                self.scroll_frame, text=line, font=self.font_small,
                fg=color, bg=RELIC_BG, anchor="w", padx=4, pady=0,
            ).pack(fill="x", padx=4, pady=0)

        if without_short:
            names = ", ".join(r.name for r in without_short)
            tk.Label(
                self.scroll_frame, text=f"  Other: {names}", font=self.font_small,
                fg="#888", bg=RELIC_BG, anchor="w", padx=4, pady=2,
            ).pack(fill="x", padx=4, pady=0)

    # ── Merchant Relics ──────────────────────────────────────────

    def _render_merchant_relics(self, merchant_relics: list[MerchantRelic]):
        tk.Label(
            self.scroll_frame,
            text=f"\U0001F6D2  MERCHANT RELICS ({len(merchant_relics)})",
            font=self.font_header, fg="#ffcc00", bg="#2a2a1e",
            anchor="w", padx=8, pady=4,
        ).pack(fill="x", pady=(10, 2))

        for mr in sorted(merchant_relics, key=lambda r: rarity_sort_key(r.rarity)):
            color = rarity_color(mr.rarity)
            short = strip_bbcode(get_short_description_only(mr.name))

            line = f"  {mr.name}  \u2022 {mr.rarity.upper()}  \u2022 {mr.cost}g"
            if short:
                line += f"  \u2022 {short}"

            tk.Label(
                self.scroll_frame, text=line, font=self.font_body,
                fg=color, bg="#1e1e2e", anchor="w", padx=8, pady=3,
                wraplength=WINDOW_WIDTH - 20, justify="left",
            ).pack(fill="x", padx=4, pady=1)

    def run(self):
        """Start the Tkinter event loop."""
        self.root.mainloop()
