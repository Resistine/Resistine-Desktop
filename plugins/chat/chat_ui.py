"""Chat UI construction mixin for the Chat plugin."""
from __future__ import annotations

import sys
import tkinter

import customtkinter

from plugins.chat.assistant_bubble import AssistantBubble
from plugins.chat.bubble import BubbleRow, UserBubble, assistant_width, user_width
from plugins.chat.fonts import RESISTINE_BLUE, _is_dark_mode, ui_family
from plugins.chat.sidebar import ChatSidebar
from plugins.chat.welcome_screen import (
    ApiKeyMissingScreen, ChatLockedScreen, WelcomeScreen)
from utils.emoji_entry import EmojiEntry

# Opacity of the layer that dims the chat behind the open history drawer.
# 0 = invisible, 1 = solid black; this is the "slightly darker" look.
_DIM_ALPHA = 0.4


# Symbol-capable UI font for glyph buttons (send arrow, menu, scroll-down).
# These buttons set no family, so CTkFont falls back to the theme family
# "Inter" — not installed on Windows, so Tk substitutes an inconsistent glyph
# for the arrow/dingbat codepoints. "Segoe UI Symbol" ships on every supported
# Windows and draws U+2191/U+2630/U+25BC/U+25A0 crisply and deterministically.
# On macOS/Linux the default already renders well, so leave family unset to
# keep the current appearance exactly (zero visual change off Windows).
_GLYPH_FAMILY = "Segoe UI Symbol" if sys.platform.startswith("win") else None


def _glyph_font(size: int, weight: str = "normal") -> customtkinter.CTkFont:
    """CTkFont for glyph buttons; symbol-capable + deterministic on Windows."""
    if _GLYPH_FAMILY is not None:
        return customtkinter.CTkFont(
            family=_GLYPH_FAMILY, size=size, weight=weight)
    return customtkinter.CTkFont(size=size, weight=weight)


class ChatUIMixin:
    """UI construction methods mixed into the Chat Plugin class."""

    # Drawer overlay starts just below the header bar (header sits at y=4..46).
    _DRAWER_TOP = 46

    def create_main_screen(self):
        is_dark = _is_dark_mode()
        self._ensure_session()

        self.second_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent")

        # Access gate: chat is only available when the VPN is connected AND the
        # Endpoint agent is installed. Re-checked on every navigation to chat
        # (the screen isn't cached), so it unlocks as soon as both are ready.
        vpn_on, agent_installed = self._chat_access_status()
        if not (vpn_on and agent_installed):
            self._build_locked_screen(is_dark, vpn_on, agent_installed)
            return self.second_frame

        # Build the full-width chat area first. The history sidebar is an
        # OVERLAY drawer over this area (see _show_sidebar) rather than a packed
        # column — so toggling it never resizes/reflows the chat content and the
        # markdown bubbles never re-wrap. That eliminates the toggle jaggedness.
        self._build_chat_area(is_dark)

        self._sidebar = ChatSidebar(
            self.second_frame,
            on_select=self._select_chat,
            on_new_chat=self._new_chat,
            on_delete=self._delete_chat,
            is_dark=is_dark)
        # Same fix as the chat-area caches above. The screen isn't cached
        # (no screen_signature), so navigation away+back builds a new
        # ChatSidebar — but _drawer_placed=True from the dead instance
        # would skip the .place() call in _sync_drawer_geometry, leaving
        # the fresh drawer constructed-but-never-positioned. Same for
        # _last_drawer_h: a height match against the new chat-area would
        # gate out the configure() call and the drawer would render
        # short or zero-height.
        self._drawer_placed = False
        self._last_drawer_h = None
        # Keep the open drawer sized to the chat area as the window resizes.
        self.second_frame.bind(
            "<Configure>", self._on_second_frame_configure, add="+")
        # The dim layer is a separate top-level window, so it must follow the
        # chat screen's visibility: hide it when this screen is unmapped
        # (navigated away / minimized), re-show it on return if the drawer is
        # still open.
        self.second_frame.bind("<Unmap>", self._on_chat_unmapped, add="+")
        self.second_frame.bind("<Map>", self._on_chat_mapped, add="+")
        if self._sidebar_visible:
            self._show_sidebar()

        self._refresh_sidebar()
        return self.second_frame

    # -- Access gate (VPN + endpoint agent) --------------------------------

    def _chat_access_status(self) -> tuple[bool, bool]:
        """Return (vpn_connected, endpoint_agent_installed) for the gate.

        Note: the endpoint check is "installed" (not "running") on purpose.
        Falls back to the VPN plugin's status badge if the helper is missing.
        """
        vpn_on = False
        try:
            from plugins.vpn.main import is_vpn_connected
            vpn_on = bool(is_vpn_connected())
        except Exception:
            try:
                vp = next(
                    (p for p in self.app.plugin_list
                     if p.get_name() == "VPN"), None)
                vpn_on = bool(vp and vp.get_status() == "OK")
            except Exception:
                vpn_on = False
        agent_installed = False
        try:
            from plugins.wazuh.main import is_agent_installed
            agent_installed = bool(is_agent_installed())
        except Exception:
            agent_installed = False
        return vpn_on, agent_installed

    def _build_locked_screen(
        self, is_dark: bool, vpn_on: bool, agent_installed: bool,
    ) -> None:
        screen = ChatLockedScreen(
            self.second_frame, vpn_on, agent_installed,
            on_open_vpn=lambda: self._open_plugin("VPN"),
            on_open_endpoint=lambda: self._open_plugin("Endpoint"),
            is_dark=is_dark)
        screen.place(relx=0.5, rely=0.5, anchor="center")

    def _open_plugin(self, name: str) -> None:
        """Navigate to another plugin's screen by its display name."""
        try:
            p = next(
                (p for p in self.app.plugin_list
                 if p.get_name() == name), None)
            if p is not None:
                self.app.select_frame_by_name(
                    f"frame_{name}", button=p.get_button())
        except Exception:
            pass

    def _on_chat_unmapped(self, _event=None) -> None:
        # <Unmap> fires for the second_frame on real navigation away from
        # chat, but ALSO bubbles up from any descendant being unmapped
        # (CTk briefly unmaps widgets during reparent/restack). Filter to
        # the second_frame itself, and skip transient unmaps where the
        # frame is still viewable.
        if _event is not None and _event.widget is not self.second_frame:
            return
        try:
            if self.second_frame.winfo_viewable():
                return
        except Exception:
            pass
        # Real navigation away: hide the dim Toplevel so it doesn't linger
        # on top of the dashboard. Preserve _sidebar_visible so returning
        # to chat restores the drawer in its previous state.
        if getattr(self, "_ov_mapped", False):
            try:
                self._dim_overlay.withdraw()
                self._ov_mapped = False
            except Exception:
                pass

    def _on_chat_mapped(self, _event=None) -> None:
        # Mirror filter on _on_chat_unmapped.
        if _event is not None and _event.widget is not self.second_frame:
            return
        # If the drawer was open before navigation, re-show the dim layer
        # to match. _set_chat_dim is idempotent.
        if getattr(self, "_sidebar_visible", False):
            try:
                self._set_chat_dim(True)
            except Exception:
                pass

    def _on_second_frame_configure(self, _event=None) -> None:
        # Only react when our own frame resizes — bubble / child <Configure>
        # events bubble up here through bindtags and would otherwise re-fire
        # the layout cascade O(bubble_count) times per resize pixel.
        if _event is not None and _event.widget is not self.second_frame:
            return
        if not self._sidebar_visible:
            return
        # Debounce: window-edge drag fires Configure at 60Hz. Coalesce to one
        # drawer-resize per ~16ms so we don't spam configure()/place() calls.
        prev = getattr(self, "_sf_cfg_after", None)
        if prev is not None:
            try:
                self.second_frame.after_cancel(prev)
            except Exception:
                pass
        try:
            self._sf_cfg_after = self.second_frame.after(
                16, self._apply_drawer_layout)
        except Exception:
            self._sf_cfg_after = None

    def _apply_drawer_layout(self) -> None:
        self._sf_cfg_after = None
        try:
            if self._sidebar is None or not self._sidebar.winfo_ismapped():
                return
            self._sync_drawer_geometry()
            # Re-size + reposition the dim Toplevel for the new chat-area
            # bounds. _position_dim_overlay short-circuits if nothing
            # actually changed since the last call, so the Configure burst
            # of a window-edge drag still costs at most one WM round-trip
            # per ~16ms.
            self._position_dim_overlay()
        except Exception:
            pass

    def _build_chat_area(self, is_dark: bool) -> None:
        self._chat_area = customtkinter.CTkFrame(
            self.second_frame, corner_radius=0, fg_color="transparent")
        self._chat_area.pack(side="left", fill="both", expand=True)
        self._chat_area.grid_columnconfigure(0, weight=1)
        self._chat_area.grid_rowconfigure(0, weight=1)

        self.chat_scroll = customtkinter.CTkScrollableFrame(
            self._chat_area, fg_color="transparent", corner_radius=0)
        # Left buffer so content doesn't touch the edge, but NO right padding so
        # the scrollbar stays flush with the right side of the window (its width
        # already separates the content from the edge).
        self.chat_scroll.grid(
            row=0, column=0, padx=(14, 0), pady=(50, 76), sticky="nsew")
        # Hide scrollbar initially; show only when content overflows
        self._hide_scrollbar()
        # Reset every cache that's keyed on the prior widget instances.
        # These live on the Plugin (not on second_frame), so navigation
        # away+back would otherwise let stale state from the destroyed
        # CTkScrollableFrame block visibility / sizing in the fresh one:
        # _scrollbar_currently_shown=True would gate out _show_scrollbar
        # on the next overflow, _last_avail==N would gate out the bubble
        # walk if the new chat happens to land at the same width.
        self._scrollbar_currently_shown = False
        self._last_avail = None

        self._bubble_rows.clear()
        self._welcome_frame = None
        self._bottom_spacer: customtkinter.CTkFrame | None = None
        self._current_asst_bubble: AssistantBubble | None = None
        self._header_visible = False
        self._header_label = None
        self._build_input_bar(is_dark)
        self._build_overlay_buttons(is_dark)
        self._restore_history(is_dark)
        self.chat_scroll.bind("<Configure>", self._on_resize, add="+")
        try:
            canvas = self.chat_scroll._parent_canvas
            # Debounced scroll-button check on wheel: cancel the previous
            # scheduled call so a 10-notch burst fires _check_scroll_btn
            # ONCE (100 ms after the last notch), not 10 times.
            canvas.bind(
                "<MouseWheel>", self._schedule_scroll_btn_check, add="+")
            canvas.bind(
                "<Button-4>", self._schedule_scroll_btn_check, add="+")
            canvas.bind(
                "<Button-5>", self._schedule_scroll_btn_check, add="+")
            if sys.platform.startswith("win"):
                # CTk sets yscrollincrement=1 on Windows, so the wheel only
                # moves ~20px per notch (delta/6 units * 1px) — too slow, and
                # it feels even slower on long chats. Bump the increment so each
                # notch moves a comfortable, FIXED ~100px regardless of page
                # length (delta/6 = 20 units * 5px = 100px).
                try:
                    canvas.configure(yscrollincrement=5)
                except Exception:
                    pass
                # Clear residual scroll "tracers" (a Windows canvas blit
                # artifact) once the wheel burst SETTLES. Debounced on purpose:
                # the previous per-tick update_idletasks() cost grew with page
                # length and was the real cause of "slower the longer the page."
                canvas.bind("<MouseWheel>", self._win_scroll_redraw, add="+")
        except Exception:
            pass

    def _win_scroll_redraw(self, _event=None) -> None:
        """Debounced repaint to clear Windows scroll tracers after the wheel
        burst settles, without adding per-notch cost that scales with page
        length."""
        try:
            canvas = self.chat_scroll._parent_canvas
            prev = getattr(self, "_scroll_redraw_after", None)
            if prev:
                try:
                    canvas.after_cancel(prev)
                except Exception:
                    pass
            self._scroll_redraw_after = canvas.after(
                60, canvas.update_idletasks)
        except Exception:
            pass

    def _restore_history(self, is_dark: bool) -> None:
        has_history = False
        for msg in self.conversation_history:
            role, content = msg.get("role"), msg.get("content", "")
            if role == "system":
                continue
            has_history = True
            if role == "user":
                self._add_user_bubble(content, is_dark)
            elif role == "assistant":
                self._add_assistant_bubble(is_dark, md=content)
        if has_history:
            self._show_header()
            return
        if self.client is not None:
            self._welcome_frame = WelcomeScreen(
                self.chat_scroll, self._use_suggestion, is_dark)
        else:
            self._welcome_frame = ApiKeyMissingScreen(
                self.chat_scroll, self._open_settings, is_dark)
        # Modest top inset (not 80px): with widget scaling the greeting +
        # 4 suggestion chips were taller than the viewport, pushing the bottom
        # chips behind the input bar. A smaller inset keeps them all visible.
        self._welcome_frame.pack(expand=True, fill="both", pady=(24, 0))

    def _build_input_bar(self, is_dark: bool) -> None:
        fg = "#ffffff" if is_dark else "#000000"
        bg, brd = ("#1A1A1C", "#2A2A2A") if is_dark else ("#F5F5F7", "#E5E7EB")
        bar = customtkinter.CTkFrame(
            self._chat_area, fg_color=bg,
            corner_radius=22, border_width=1, border_color=brd)
        self._input_bar = bar
        bar.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.96, y=-14)
        bar.grid_columnconfigure(0, weight=1)
        self.chat_entry = EmojiEntry(
            bar, placeholder_text="Message Resistine AI...",
            corner_radius=20, border_width=0, height=44,
            font=customtkinter.CTkFont(family=ui_family(), size=16),
            fg_color="transparent", text_color=fg,
            placeholder_text_color="#8ea8c6" if is_dark else "#9aa5b1")
        self.chat_entry.grid(
            row=0, column=0, padx=(16, 4), pady=0, sticky="ew")
        self.send_button = customtkinter.CTkButton(
            bar, text="\u2191", command=self.send_message,
            corner_radius=18, height=36, width=36,
            font=_glyph_font(18, weight="bold"),
            fg_color=RESISTINE_BLUE, hover_color="#1565B0",
            text_color="#ffffff")
        self.send_button.grid(row=0, column=1, padx=(0, 6), pady=6)
        self.chat_entry.bind("<Return>", lambda _e: self.send_message())
        if self.client is None:
            self.chat_entry.configure(
                state="disabled",
                placeholder_text="API key required \u2014 see Settings")
            self.send_button.configure(state="disabled", fg_color="#6B7280")

    def _build_overlay_buttons(self, is_dark: bool) -> None:
        fg = "#e0e0e0" if is_dark else "#1a1a1a"
        btn_bg = "#2A2A2C" if is_dark else "#E8E8EA"
        hover_bg = "#3A3A3C" if is_dark else "#D8D8DC"

        # Header bar with menu button, title, and new chat button
        header = customtkinter.CTkFrame(
            self._chat_area, fg_color="transparent", height=42)
        header.place(relx=0, rely=0, relwidth=1.0, y=4)
        header.grid_columnconfigure(1, weight=1)

        btn_size = 32
        self._toggle_btn = customtkinter.CTkButton(
            header, text="\u2630", width=btn_size, height=btn_size,
            corner_radius=8, fg_color=btn_bg, hover_color=hover_bg,
            text_color=fg,
            font=_glyph_font(16),
            command=self._toggle_sidebar)
        self._toggle_btn.grid(row=0, column=0, padx=(12, 0), pady=4)

        self._header_label = customtkinter.CTkLabel(
            header, text="Resistine AI",
            font=customtkinter.CTkFont(
                family=ui_family(), size=16, weight="bold"),
            text_color=fg, fg_color="transparent")
        self._header_label.grid(row=0, column=1, pady=4)
        self._header_visible = True

        self._new_chat_btn = customtkinter.CTkButton(
            header, text="+", width=btn_size, height=btn_size,
            corner_radius=8, fg_color=btn_bg, hover_color=hover_bg,
            text_color=fg,
            font=customtkinter.CTkFont(size=20, weight="bold"),
            command=self._new_chat)
        self._new_chat_btn.grid(row=0, column=2, padx=(0, 12), pady=4)

        self._scroll_btn = customtkinter.CTkButton(
            self._chat_area, text="\u25bc", width=30, height=30,
            corner_radius=15,
            fg_color=RESISTINE_BLUE, hover_color="#1565B0",
            text_color="#ffffff",
            font=_glyph_font(10),
            command=self._scroll_to_bottom)
        self._scroll_btn_visible = False

    def _show_sidebar(self) -> None:
        """Reveal the history drawer as an overlay on the left of the chat area.

        It floats over the chat (below the header bar) instead of pushing it, so
        the chat content keeps its width and never re-wraps.
        """
        # Single source of truth for the open-state: every show/hide path
        # (toggle button, clicking the dim overlay, navigation) updates it here
        # so it can never go stale. Closing via the overlay used to leave this
        # True, which re-opened the drawer on the next chat rebuild (+ New).
        self._sidebar_visible = True
        # Place the drawer first — the dim overlay is sized to the full app
        # window (see _position_dim_overlay), so no need to wait on drawer
        # geometry. Avoid update_idletasks() here: it re-enters the event
        # loop in the middle of a toggle and can crash mid-rebuild.
        self._sync_drawer_geometry()
        self._set_chat_dim(True)
        # Raise the drawer above the dim layer on every show. CTk's place()
        # alone doesn't guarantee a Toplevel ends up below — explicit lift
        # makes the drawer the topmost widget within the App window, while
        # the dim Toplevel sits above the chat content.
        try:
            self._sidebar.lift()
        except Exception:
            pass

    def _set_chat_dim(self, dim: bool) -> None:
        """Show/hide the dim layer over the chat while the drawer is open.

        We use a borderless alpha Toplevel positioned to cover the chat to
        the RIGHT of the drawer (NOT the drawer area itself). Toplevels
        always render above in-process Frames regardless of .lift() calls,
        so an overlay positioned over the drawer would block clicks on it
        and visually dim it. Sizing the overlay to exclude the drawer
        sidesteps the z-order limitation entirely.
        """
        ov = self._ensure_dim_overlay()
        if ov is None:
            return
        if dim:
            if self._position_dim_overlay():
                # Only deiconify on the False→True transition. deiconify is
                # a WM round-trip that on Windows triggers extra paints when
                # called on an already-mapped window.
                if not getattr(self, "_ov_mapped", False):
                    try:
                        ov.deiconify()
                        ov.lift()
                        self._ov_mapped = True
                    except Exception:
                        pass
        else:
            if getattr(self, "_ov_mapped", False):
                try:
                    ov.withdraw()
                    self._ov_mapped = False
                except Exception:
                    pass

    def _ensure_dim_overlay(self):
        """Create the dim layer once (borderless, alpha). Returns it or None."""
        ov = getattr(self, "_dim_overlay", None)
        try:
            if ov is not None and ov.winfo_exists():
                return ov
        except Exception:
            pass
        try:
            ov = tkinter.Toplevel(self.app)
            ov.overrideredirect(True)       # borderless; no taskbar/focus steal
            ov.configure(bg="#000000")
            try:
                ov.attributes("-alpha", _DIM_ALPHA)
            except Exception:
                pass
            try:
                ov.transient(self.app)      # stack + minimize with the main win
            except Exception:
                pass
            ov.withdraw()
            self._ov_mapped = False
            # Clicking the dimmed area collapses the drawer; being on top, the
            # overlay also blocks hover on everything beneath it.
            ov.bind("<Button-1>", lambda _e: self._hide_sidebar())
            self._dim_overlay = ov
            self._last_ov_geom = None
            # second_frame <Configure> fires on resize but not on a window
            # move, so also track the top-level window's geometry. Bind ONCE
            # (across chat rebuilds) and let _on_app_configure debounce.
            if not getattr(self, "_app_cfg_bound", False):
                try:
                    self._app_cfg_bid = self.app.bind(
                        "<Configure>", self._on_app_configure, add="+")
                    self._app_cfg_bound = True
                except Exception:
                    pass
        except Exception:
            self._dim_overlay = None
        return self._dim_overlay

    def _position_dim_overlay(self) -> bool:
        """Size the overlay to cover the chat area to the RIGHT of the
        drawer (not the drawer itself). Returns False if not yet laid out.

        Both winfo_rootx/y/width/height and Toplevel.geometry() use the
        same coordinate system on every platform — Tk's logical pixel
        space, which Tk itself maps to OS pixels via tk scaling. No
        manual rescaling needed: a verified empirical check on macOS
        Retina (tk_scaling ≈ 1.0), Linux HiDPI (CTk window_scaling=1.5
        with winfo already reporting the post-scaling number), and
        Windows DPI-aware (tk_scaling ≈ 1.33+) all show geometry()
        accepting the same units winfo_* reports. The prior multiplier
        produced a 33-78% overshoot, leaving the chat top-and-left
        undimmed (the exact symptom this method was meant to cure).
        """
        ov = getattr(self, "_dim_overlay", None)
        if ov is None:
            return False
        try:
            # winfo_* is already current inside <Configure> handlers — do
            # NOT call update_idletasks() here (re-entry hazard).
            sf = self.second_frame
            x = sf.winfo_rootx()
            y = sf.winfo_rooty()
            w = sf.winfo_width()
            h = sf.winfo_height()
            # Drawer width: actual mapped width if available, else its
            # advertised _WIDTH constant.
            sb = getattr(self, "_sidebar", None)
            try:
                drawer_w = (sb.winfo_width() if sb and sb.winfo_ismapped()
                            else getattr(sb, "_WIDTH", 220))
            except Exception:
                drawer_w = getattr(sb, "_WIDTH", 220) if sb else 220
            ox = x + drawer_w
            ow = w - drawer_w
            if ow <= 1 or h <= 1:
                return False
            geom = (ow, h, ox, y)
            # Skip the WM round-trip if nothing changed since last call.
            if getattr(self, "_last_ov_geom", None) == geom:
                return True
            self._last_ov_geom = geom
            ov.geometry(f"{ow}x{h}+{ox}+{y}")
            return True
        except Exception:
            return False

    def _on_app_configure(self, _event=None) -> None:
        # Only react to the App top-level itself moving — every descendant
        # Configure bubbles through here too (bindtag includes toplevel
        # pathname), which on a long chat fires O(bubble_count) times per
        # drag pixel. Filter aggressively.
        if _event is None or _event.widget is not self.app:
            return
        if not getattr(self, "_ov_mapped", False):
            return
        # Debounce to one reposition per ~16ms frame instead of per drag pixel.
        prev = getattr(self, "_app_cfg_after", None)
        if prev is not None:
            try:
                self.app.after_cancel(prev)
            except Exception:
                pass
        try:
            self._app_cfg_after = self.app.after(
                16, self._position_dim_overlay)
        except Exception:
            self._app_cfg_after = None

    def _sync_drawer_geometry(self) -> None:
        """Size + place the drawer to fill the chat area below the header.

        CTk's place() refuses an absolute height (it must be set via the
        constructor / configure()), so we configure() the height and only pass
        x/y to place(). Width comes from the ChatSidebar constructor.

        Idempotent: skip the configure() round-trip when the height hasn't
        actually changed (e.g. window moved but didn't resize).
        """
        try:
            h = max(1, self.second_frame.winfo_height() - self._DRAWER_TOP)
            if getattr(self, "_last_drawer_h", None) != h:
                self._sidebar.configure(height=h)
                self._last_drawer_h = h
            # place() is a no-op when x/y unchanged but Tk still issues a
            # WM placement command; call it only on the first show.
            if not getattr(self, "_drawer_placed", False):
                self._sidebar.place(x=0, y=self._DRAWER_TOP)
                self._drawer_placed = True
        except Exception:
            pass

    def _hide_sidebar(self) -> None:
        # Single source of truth — see _show_sidebar. Clear it here so closing
        # via the dim-overlay click (which calls _hide_sidebar directly, NOT
        # _toggle_sidebar) doesn't leave a stale "open" flag.
        self._sidebar_visible = False
        self._set_chat_dim(False)
        try:
            if getattr(self, "_sidebar", None) is not None:
                self._sidebar.place_forget()
        except Exception:
            pass
        # Reset the place-once latch so the next show re-places the drawer.
        self._drawer_placed = False

    def _toggle_sidebar(self) -> None:
        # _show_sidebar / _hide_sidebar own _sidebar_visible now, so don't flip
        # it here too (that would double-toggle).
        if self._sidebar_visible:
            self._hide_sidebar()
        else:
            self._show_sidebar()

    def _schedule_scroll_btn_check(self, _event=None) -> None:
        """Debounce wrapper for _check_scroll_btn — fires 100 ms after the
        last wheel notch instead of once per notch."""
        prev = getattr(self, "_scroll_btn_after", None)
        if prev is not None:
            try:
                self.chat_scroll.after_cancel(prev)
            except Exception:
                pass
        try:
            self._scroll_btn_after = self.chat_scroll.after(
                100, self._check_scroll_btn_fire)
        except Exception:
            self._scroll_btn_after = None

    def _check_scroll_btn_fire(self) -> None:
        self._scroll_btn_after = None
        self._check_scroll_btn()

    def _check_scroll_btn(self) -> None:
        if not hasattr(self, "_scroll_btn") or self._scroll_btn is None:
            return
        near = self._is_near_bottom()
        if not near and not self._scroll_btn_visible:
            try:
                self._scroll_btn.place(
                    relx=0.5, rely=1.0, anchor="s", y=-72)
                self._scroll_btn_visible = True
            except Exception:
                pass
        elif near and self._scroll_btn_visible:
            try:
                self._scroll_btn.place_forget()
            except Exception:
                pass
            self._scroll_btn_visible = False

    def _refresh_sidebar(self) -> None:
        if hasattr(self, "_sidebar") and self._sidebar:
            self._sidebar.refresh(
                self._history.list_sessions(),
                self._history.get_active_id())

    def _show_header(self) -> None:
        if not self._header_visible and self._header_label is not None:
            self._header_label.grid(row=0, column=1, pady=4)
            self._header_visible = True

    # -- Bubble helpers ----------------------------------------------------

    def _available_width(self, *, force_idle: bool = False) -> int:
        try:
            # update_idletasks() inside a <Configure> handler re-enters the
            # event loop and can crash. winfo_* is already current during
            # a Configure event; only force idle when called from a
            # non-resize site (initial layout, after a bubble add).
            if force_idle:
                try:
                    self.chat_scroll.update_idletasks()
                except Exception:
                    pass
            # The scrollable INNER frame width is inflated by a wide wrap="none"
            # code block on Windows; the parent canvas is the true viewport and
            # is never inflated by content. Prefer it; fall back to the frame.
            try:
                w = self.chat_scroll._parent_canvas.winfo_width()
            except Exception:
                w = 0
            if w <= 1:
                w = self.chat_scroll.winfo_width()
            return max(w - 20, 300) if w > 1 else 800
        except Exception:
            return 800

    def _make_row(self) -> BubbleRow:
        if self._bottom_spacer is not None:
            self._bottom_spacer.destroy()
        row = BubbleRow(self.chat_scroll)
        self._bubble_rows.append(row)
        self._bottom_spacer = customtkinter.CTkFrame(
            self.chat_scroll, fg_color="transparent", height=16)
        self._bottom_spacer.pack(fill="x")
        return row

    def _add_user_bubble(self, text: str, is_dark: bool) -> BubbleRow:
        row = self._make_row()
        UserBubble(row, text, is_dark=is_dark,
                   max_width=user_width(self._available_width(force_idle=True)))
        return row

    def _add_assistant_bubble(
        self, is_dark: bool, md: str | None = None,
    ) -> AssistantBubble:
        row = self._make_row()
        ab = AssistantBubble(
            row, is_dark=is_dark,
            max_width=assistant_width(self._available_width(force_idle=True)))
        if md is not None:
            ab.finalize_markdown(md)
        return ab

    def _is_near_bottom(self) -> bool:
        try:
            if self.chat_scroll is None:
                return True
            return self.chat_scroll._parent_canvas.yview()[1] > 0.95
        except Exception:
            return True

    def _scroll_to_bottom(self) -> None:
        try:
            if self.chat_scroll is not None:
                self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass
        if hasattr(self, "_scroll_btn") and self._scroll_btn_visible:
            try:
                self._scroll_btn.place_forget()
            except Exception:
                pass
            self._scroll_btn_visible = False

    def _on_resize(self, _event=None) -> None:
        # Window-edge drag fires <Configure> at 60+ Hz. Coalesce to one
        # bubble-resize pass per ~30ms so each drag pixel doesn't iterate
        # every bubble. The earlier _in_on_resize re-entry guard is
        # preserved against scrollbar-toggle echoes inside _do_resize.
        prev = getattr(self, "_resize_after", None)
        if prev is not None:
            try:
                self.chat_scroll.after_cancel(prev)
            except Exception:
                pass
        try:
            self._resize_after = self.chat_scroll.after(
                30, self._do_resize)
        except Exception:
            self._resize_after = None

    def _do_resize(self) -> None:
        self._resize_after = None
        # winfo_* is current after the post-Configure tick — safe without
        # update_idletasks(), and force_idle would re-enter here.
        avail = self._available_width()
        # Short-circuit when width didn't actually change — scrollbar
        # auto-hide can echo <Configure> events that don't change the
        # available width, and walking every bubble per echo is wasted.
        if avail == getattr(self, "_last_avail", None):
            self._check_scroll_btn()
            return
        self._last_avail = avail
        if getattr(self, "_in_on_resize", False):
            return
        self._in_on_resize = True
        try:
            uw, aw = user_width(avail), assistant_width(avail)
            for row in self._bubble_rows:
                for child in row.winfo_children():
                    if isinstance(child, UserBubble):
                        child.set_width(uw)
                    elif isinstance(child, AssistantBubble):
                        child.set_width(aw)
            self._check_scroll_btn()
            self._update_scrollbar_visibility()
        finally:
            self._in_on_resize = False

    # -- Scrollbar visibility ----------------------------------------------

    def _hide_scrollbar(self) -> None:
        try:
            scrollbar = self.chat_scroll._scrollbar
            scrollbar.grid_remove()
        except Exception:
            pass

    def _show_scrollbar(self) -> None:
        try:
            scrollbar = self.chat_scroll._scrollbar
            scrollbar.grid()
        except Exception:
            pass

    def _update_scrollbar_visibility(self) -> None:
        try:
            canvas = self.chat_scroll._parent_canvas
            # No update_idletasks() here — runs inside <Configure>; bbox is
            # already current. The forced flush was the source of an echo
            # <Configure> that re-fired _on_resize twice per drag pixel.
            bbox = canvas.bbox("all")
            if not bbox:
                desired = False
            else:
                content_h = bbox[3] - bbox[1]
                visible_h = canvas.winfo_height()
                desired = content_h > visible_h
            # Idempotent: skip grid()/grid_remove() (and the <Configure>
            # echo they cause on the canvas) when state is unchanged.
            cur = getattr(self, "_scrollbar_currently_shown", None)
            if desired == cur:
                return
            self._scrollbar_currently_shown = desired
            if desired:
                self._show_scrollbar()
            else:
                self._hide_scrollbar()
        except Exception:
            pass

    # -- Scroll to last user bubble ----------------------------------------

    def _scroll_to_last_user_bubble(self) -> None:
        """Scroll so the last user message is at the top of the view."""
        try:
            canvas = self.chat_scroll._parent_canvas
            canvas.update_idletasks()
            # Find the last user bubble row
            last_user_row = None
            for row in self._bubble_rows:
                for child in row.winfo_children():
                    if isinstance(child, UserBubble):
                        last_user_row = row
                        break
            if last_user_row is None:
                return
            # Get the y position of the user row relative to the scroll content
            row_y = last_user_row.winfo_y()
            bbox = canvas.bbox("all")
            if not bbox:
                return
            content_h = bbox[3] - bbox[1]
            if content_h <= 0:
                return
            # Scroll so the user row is near the top (with a small offset)
            frac = max(0.0, (row_y - 8) / content_h)
            canvas.yview_moveto(frac)
        except Exception:
            self._scroll_to_bottom()
