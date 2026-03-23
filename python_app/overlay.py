from __future__ import annotations

import ctypes
import platform
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable
from pathlib import Path
import time

from .utils import strip_bbcode

try:
    import keyboard as kb
except ImportError:
    kb = None

from .combat_engine import (
    calculate_incoming_damage,
    summarize_hand,
)
from .strategy import compute_strategy
from .models import GameState, MerchantRelic, Relic
from .data_parser import load_reward_state
from .reward_advisor import recommend
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
OVERLAY_ALPHA = 0.90
WINDOW_WIDTH = 460
WINDOW_HEIGHT = 720
MIN_WIDTH = 320
MAX_WIDTH = 900
MIN_HEIGHT = 400
MAX_HEIGHT = 1200
RESIZE_GRIP_SIZE = 14
WARN_HP_THRESHOLD = 0.3


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
GHOST_ALPHA = 0.55
# Force the shell to apply GWL_EXSTYLE changes (otherwise click-through often "sticks")
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
GHOST_TOGGLE_DEBOUNCE_S = 0.22


def _win32_refresh_window_frame(hwnd: int) -> None:
    """Notify Windows that non-client / extended style changed."""
    if platform.system() != "Windows" or not hwnd:
        return
    ctypes.windll.user32.SetWindowPos(
        hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )


def _overlay_win32_hwnds(root: tk.Tk) -> list[int]:
    """Tk may use a child HWND + parent toplevel; both may need EXSTYLE updates."""
    if platform.system() != "Windows":
        return []
    root.update_idletasks()
    cid = int(root.winfo_id())
    user32 = ctypes.windll.user32
    out: list[int] = [cid]
    parent = user32.GetParent(cid)
    if parent:
        out.append(int(parent))
    return out


def _set_click_through(hwnd: int, enable: bool):
    """Toggle click-through on a Win32 window handle."""
    if platform.system() != "Windows" or not hwnd:
        return
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enable:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    _win32_refresh_window_frame(hwnd)


class CombatOverlay:
    """Semi-transparent always-on-top overlay showing combat calculations."""

    def __init__(self, on_close: Callable[[], None] | None = None, debug: bool = False):
        self.root = tk.Tk()
        self.root.title("BoberInSpire")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", OVERLAY_ALPHA)
        self.root.configure(bg=BG_COLOR)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+50+50")

        self._ghost_mode = False
        self._last_ghost_toggle_ts = 0.0
        self._drag_data: dict = {"x": 0, "y": 0}
        self._resize_data: dict | None = None
        self._on_close = on_close
        self._debug = debug
        self._last_state: GameState | None = None
        self._last_reward_data: dict | None = None
        self._reward_file_path: str = ""
        self._reward_poll_timer: str | None = None

        self._build_fonts()
        self._build_widgets()

    def _build_fonts(self):
        self.font_title = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.font_header = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.font_net = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.font_body = tkfont.Font(family="Consolas", size=10)
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

        self._ghost_btn = tk.Label(
            title_bar, text=" \U0001F441 ", font=self.font_btn,
            fg="#aaa", bg="#0d0d1a", cursor="hand2",
        )
        self._ghost_btn.pack(side="right")
        self._ghost_btn.bind("<Button-1>", lambda e: self._toggle_ghost())

        self._hotkey_remove: Callable[[], None] | None = None
        if kb:
            try:
                self._hotkey_remove = kb.add_hotkey(
                    "f9",
                    self._schedule_toggle_ghost,
                    suppress=False,
                )
            except Exception:
                self._hotkey_remove = None
        # Avoid double-toggle: global hook + Tk both bound to F9 would flip twice per keypress.
        if self._hotkey_remove is None:
            self.root.bind("<F9>", lambda e: self._toggle_ghost())

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
            text="Waiting for game state... (F9 = ghost mode)",
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

    def _schedule_toggle_ghost(self):
        """Called from global F9 hotkey (possibly another thread); run toggle on main thread."""
        try:
            self.root.after(0, self._toggle_ghost)
        except tk.TclError:
            pass

    def _toggle_ghost(self):
        now = time.monotonic()
        if now - self._last_ghost_toggle_ts < GHOST_TOGGLE_DEBOUNCE_S:
            return
        self._last_ghost_toggle_ts = now

        self._ghost_mode = not self._ghost_mode
        hwnds = _overlay_win32_hwnds(self.root) if platform.system() == "Windows" else []

        if self._ghost_mode:
            self.root.attributes("-alpha", GHOST_ALPHA)
            for h in hwnds:
                _set_click_through(h, True)
            self._ghost_btn.configure(fg=SAFE_COLOR)
            self.status_label.configure(
                text="GHOST MODE (click-through) \u2022 F9 = back to normal (global)"
            )
        else:
            # Clear click-through before restoring alpha so hit-testing updates reliably.
            for h in hwnds:
                _set_click_through(h, False)
            self.root.attributes("-alpha", OVERLAY_ALPHA)
            self._ghost_btn.configure(fg="#aaa")
            self.status_label.configure(
                text="Interactive \u2022 F9 = ghost (works even when overlay is click-through)"
            )

    def _handle_close(self):
        if getattr(self, "_hotkey_remove", None):
            try:
                self._hotkey_remove()
            except Exception:
                pass
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
        try:
            from pathlib import Path
            p = Path(self._reward_file_path)
            if p.exists():
                data = load_reward_state(p)
                if data and data.get("options"):
                    self._last_reward_data = data
                else:
                    self._last_reward_data = None
            else:
                self._last_reward_data = None
            self._render_all()
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
            self._last_reward_data = None
        else:
            self._refresh_reward_if_needed()
        self._render_all()

    def update_reward_state(self, reward_data: dict):
        """Update overlay with reward screen data (from RewardStateWatcher)."""
        if reward_data and reward_data.get("options"):
            self._last_reward_data = reward_data
        else:
            self._last_reward_data = None
        self._render_all()

    def _refresh_reward_if_needed(self):
        """When combat state updates, also check reward file (mod may write both)."""
        if not self._reward_file_path:
            return
        try:
            from pathlib import Path
            if Path(self._reward_file_path).exists():
                data = load_reward_state(self._reward_file_path)
                if data and data.get("options"):
                    self._last_reward_data = data
        except Exception:
            pass

    def _should_show_card_reward(self) -> bool:
        """Only on post-combat card pick: have options, and not in active combat."""
        if not self._last_reward_data or not self._last_reward_data.get("options"):
            return False
        if self._last_state and self._last_state.enemies:
            return False
        return True

    def _render_all(self):
        """Re-render overlay from stored state and reward data."""
        self._clear_scroll_frame()
        state = self._last_state
        show_pick = self._should_show_card_reward()

        if show_pick:
            self._render_card_reward()

        if state:
            self._render_player_info(state)
            if not show_pick:
                self._render_enemies(state)
                self._render_strategy(state)
            self._render_relics(state)
            if state.merchant_relics and not show_pick:
                self._render_merchant_relics(state.merchant_relics)

        if self._debug:
            self._render_debug()

        if show_pick:
            self.status_label.config(text="Choose a Card  |  Reward advisor")
        elif state:
            self.status_label.config(text=f"Turn {state.turn}  |  Updated")
        else:
            self.status_label.config(text="Waiting for game state... (F9 = ghost mode)")
        self.root.after(50, self._update_scrollbar_visibility)

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

        opts = (self._last_reward_data or {}).get("options") or []
        opts_preview = ", ".join(str(x) for x in opts[:3])
        if len(opts) > 3:
            opts_preview += f", …(+{len(opts)-3})"

        lines = [
            f"Reward file: {self._reward_file_path or '(not set)'}",
            f"Exists: {exists}  MTime: {mtime or '-'}  Size: {size or '-'}",
            f"Parsed options: {len(opts)}  [{opts_preview}]",
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

    # ── Player info + NET damage banner ─────────────────────────

    def _render_player_info(self, state: GameState):
        p = state.player
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

        # Prominent NET damage banner — always visible
        if state.enemies and incoming.total_incoming > 0:
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
        elif state.enemies:
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

    def _render_enemies(self, state: GameState):
        if not state.enemies:
            return

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
        data = self._last_reward_data
        if not data or not data.get("options"):
            return

        tk.Label(
            self.scroll_frame, text="CHOOSE A CARD",
            font=self.font_header, fg=LETHAL_COLOR, bg="#1a2a4a", anchor="w", padx=8, pady=4,
        ).pack(fill="x", pady=(0, 2))

        rec = recommend(
            character=data.get("character", "Unknown"),
            deck=data.get("deck", []),
            relics=data.get("relics", []),
            options=data.get("options", []),
        )

        tk.Label(
            self.scroll_frame, text="CARD REWARD",
            font=self.font_header, fg="#fff", bg="#1a2a4a", anchor="w", padx=8, pady=3,
        ).pack(fill="x", pady=(4, 1))

        best = rec.best_card
        for r in rec.recommendations:
            is_best = r.name == best
            tier_color = (
                SAFE_COLOR
                if r.tier == "S"
                else WARN_COLOR
                if r.tier == "A"
                else "#a8c4e8"
                if r.tier == "B"
                else "#c9a86c"
                if r.tier == "C"
                else "#b08080"
                if r.tier == "D"
                else "#888"
            )
            prefix = "  \u2714 BEST  " if is_best else f"  {r.tier}  "
            line = f"{prefix} {r.name}  ({r.score})"
            tk.Label(
                self.scroll_frame, text=line, font=self.font_body,
                fg=tier_color if is_best else "#aaa", bg=CARD_COLOR,
                anchor="w", padx=10, pady=1,
            ).pack(fill="x", padx=4, pady=1)
            tk.Label(
                self.scroll_frame, text=f"      \u2022 {r.reason}",
                font=self.font_small, fg="#888", bg=BG_COLOR,
                anchor="w", padx=10, pady=0, wraplength=WINDOW_WIDTH - 30, justify="left",
            ).pack(fill="x", padx=4)

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
