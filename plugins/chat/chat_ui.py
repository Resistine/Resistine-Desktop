"""Chat UI construction mixin for the Chat plugin."""
from __future__ import annotations

import sys
import tkinter

import customtkinter

from plugins.chat.assistant_bubble import AssistantBubble
from plugins.chat.bubble import BubbleRow, UserBubble, assistant_width, user_width
from plugins.chat.fonts import RESISTINE_BLUE, _is_dark_mode, ui_family
from plugins.chat.sidebar import ChatSidebar
from plugins.chat.welcome_screen import ApiKeyMissingScreen, WelcomeScreen
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
        # Persistent floating bar that hosts the hamburger toggle. It caps the
        # top of the drawer (filling the header strip the dim overlay doesn't
        # reach) when open, and is a bare floating hamburger over the chat when
        # closed. Built once here so it survives chat rebuilds without flicker.
        self._build_toggle_bar(is_dark)
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

    def _on_chat_unmapped(self, _event=None) -> None:
        # Navigated away (or minimized): fully collapse the history drawer so
        # returning to chat doesn't greet the user with the dimmed overlay still
        # up. _hide_sidebar withdraws the dim layer and forgets the drawer; we
        # also clear the open-state so the rebuild/remap doesn't re-open it.
        if getattr(self, "_sidebar_visible", False):
            try:
                self._hide_sidebar()
            except Exception:
                pass
            self._sidebar_visible = False
        else:
            ov = getattr(self, "_dim_overlay", None)
            try:
                if ov is not None:
                    ov.withdraw()
            except Exception:
                pass

    def _on_chat_mapped(self, _event=None) -> None:
        # The drawer is collapsed on unmap, so there's nothing to restore here;
        # kept as a no-op guard in case the open-state is set some other way.
        if getattr(self, "_sidebar_visible", False):
            try:
                self._set_chat_dim(True)
            except Exception:
                pass

    def _on_second_frame_configure(self, _event=None) -> None:
        try:
            if self._sidebar is not None and self._sidebar.winfo_ismapped():
                self._sync_drawer_geometry()
                # Keep the dim overlay aligned to the chat as it resizes, and
                # ensure it's shown (covers the case where the chat wasn't sized
                # yet when the drawer first opened).
                if self._position_dim_overlay():
                    ov = getattr(self, "_dim_overlay", None)
                    if ov is not None:
                        ov.deiconify()
                        ov.lift()
        except Exception:
            pass

    def _build_chat_area(self, is_dark: bool) -> None:
        self._chat_area = customtkinter.CTkFrame(
            self.second_frame, corner_radius=0, fg_color="transparent")
        self._chat_area.pack(side="left", fill="both", expand=True)
        # On a REBUILD (chat switch / new / delete) the history drawer already
        # exists as a sibling of second_frame. A freshly-packed widget stacks
        # ABOVE its siblings, so the new chat area would cover the open drawer
        # for the duration of the (heavy) history restore — the menu appears to
        # vanish for a moment and the drawer's column flashes bright (the dim
        # overlay intentionally doesn't cover the drawer, so covered-drawer ==
        # a visible "gap" in the dimming). Lower the chat area BELOW the drawer
        # NOW, before any repaint, so the drawer stays on top throughout the
        # rebuild. No-op on the initial build (the drawer is created after this
        # and is naturally on top); guarded for the full-rebuild path where
        # self._sidebar may briefly point at a destroyed widget.
        if getattr(self, "_sidebar_visible", False):
            sb = getattr(self, "_sidebar", None)
            try:
                if sb is not None and sb.winfo_exists():
                    self._chat_area.lower(sb)
            except Exception:
                pass
        # The freshly-packed chat area also stacks above the persistent floating
        # toggle bar; re-raise it so the hamburger stays on top after a rebuild.
        # No-op on the initial build (the bar is created right after this).
        self._raise_toggle_bar()
        self._chat_area.grid_columnconfigure(0, weight=1)
        self._chat_area.grid_rowconfigure(0, weight=1)

        self.chat_scroll = customtkinter.CTkScrollableFrame(
            self._chat_area, fg_color="transparent", corner_radius=0)
        self.chat_scroll.grid(
            row=0, column=0, padx=0, pady=(50, 76), sticky="nsew")
        # Hide scrollbar initially; show only when content overflows
        self._hide_scrollbar()

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
            canvas.bind(
                "<MouseWheel>",
                lambda _e: self.chat_scroll.after(
                    100, self._check_scroll_btn),
                add="+")
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
        self._welcome_frame.pack(expand=True, fill="both", pady=(80, 0))

    def _build_input_bar(self, is_dark: bool) -> None:
        fg = "#ffffff" if is_dark else "#000000"
        bg, brd = ("#1A1A1C", "#2A2A2A") if is_dark else ("#F5F5F7", "#E5E7EB")
        bar = customtkinter.CTkFrame(
            self._chat_area, fg_color=bg,
            corner_radius=22, border_width=1, border_color=brd)
        self._input_bar = bar
        bar.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.98, y=-14)
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
        # The hamburger toggle lives in the persistent floating _toggle_bar
        # (built in create_main_screen) so it stays above the drawer and never
        # flickers on rebuild. Reserve its slot here so the title stays centered.
        spacer = customtkinter.CTkFrame(
            header, fg_color="transparent", width=btn_size, height=btn_size)
        spacer.grid(row=0, column=0, padx=(12, 0), pady=4)

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

    def _build_toggle_bar(self, is_dark: bool) -> None:
        """Persistent floating bar (sibling of the chat area) holding the
        hamburger toggle.

        Closed: transparent and only wide enough for the button \u2014 a bare
        floating hamburger over the chat. Open: dark and as wide as the drawer
        so it caps the drawer's top and fills the header strip the dim overlay
        deliberately leaves uncovered (the source of the bright "gap"). Living
        outside _chat_area keeps it ABOVE the drawer and unaffected by chat
        rebuilds, so the hamburger is always visible and clickable.
        """
        # Drawer background, so the open cap is seamless with the drawer below.
        self._toggle_bar_bg = "#161618" if is_dark else "#ECECEE"
        btn_bg = "#2A2A2C" if is_dark else "#E8E8EA"
        hover_bg = "#3A3A3C" if is_dark else "#D8D8DC"
        fg = "#e0e0e0" if is_dark else "#1a1a1a"
        # Height overlaps the drawer top by 2px: at fractional scaling (e.g.
        # 46*1.25=57.5) Tk rounds the cap height and the drawer's place-y
        # independently, so a tiny overlap guarantees no 1px bright sliver at the
        # seam. The cap is the same color as the drawer and lifted above it, so
        # the overlap is invisible.
        self._toggle_bar = customtkinter.CTkFrame(
            self.second_frame, fg_color="transparent",
            width=56, height=self._DRAWER_TOP + 2, corner_radius=0)
        self._toggle_bar.place(x=0, y=0)
        self._toggle_btn = customtkinter.CTkButton(
            self._toggle_bar, text="\u2630", width=32, height=32,
            corner_radius=8, fg_color=btn_bg, hover_color=hover_bg,
            text_color=fg, font=_glyph_font(16),
            command=self._toggle_sidebar)
        self._toggle_btn.place(x=12, y=7)
        self._toggle_bar.lift()

    def _raise_toggle_bar(self) -> None:
        """Re-assert the floating toggle bar's top z-order (after rebuilds)."""
        tb = getattr(self, "_toggle_bar", None)
        try:
            if tb is not None and tb.winfo_exists():
                tb.lift()
        except Exception:
            pass

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
        # Place + size the drawer FIRST so the dim overlay can measure its real
        # width and position itself to the drawer's right (not over its buttons).
        self._sync_drawer_geometry()
        try:
            self._sidebar.update_idletasks()
        except Exception:
            pass
        self._set_chat_dim(True)
        try:
            self._sidebar.lift()
        except Exception:
            pass
        # Expand the toggle bar into a dark cap as wide as the drawer so the
        # header strip above the drawer is filled (no bright gap), then raise it
        # above the drawer so the hamburger stays clickable.
        tb = getattr(self, "_toggle_bar", None)
        if tb is not None:
            try:
                tb.configure(
                    fg_color=self._toggle_bar_bg, width=self._sidebar._WIDTH)
                tb.lift()
            except Exception:
                pass

    def _set_chat_dim(self, dim: bool) -> None:
        """Show/hide the dim layer over the chat while the drawer is open.

        Instead of recoloring every widget (which Tk can't repaint atomically —
        it BitBlts each canvas one at a time), we lay a single borderless,
        semi-transparent top-level window over the chat, to the RIGHT of the
        drawer so the drawer stays bright. It darkens everything beneath it in
        one OS-composited frame (truly atomic), and being on top it also
        swallows hover and clicks — a click collapses the drawer.
        """
        ov = self._ensure_dim_overlay()
        if ov is None:
            return
        if dim:
            if self._position_dim_overlay():
                try:
                    ov.deiconify()
                    ov.lift()
                except Exception:
                    pass
        else:
            try:
                ov.withdraw()
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
            # Clicking the dimmed area collapses the drawer; being on top, the
            # overlay also blocks hover on everything beneath it.
            ov.bind("<Button-1>", lambda _e: self._hide_sidebar())
            self._dim_overlay = ov
            # second_frame <Configure> fires on resize but not on a window move,
            # so also track the top-level window's geometry. Bind ONCE — the
            # overlay can be recreated across chat rebuilds, and stacking
            # duplicate handlers would slow every resize.
            if not getattr(self, "_app_cfg_bound", False):
                try:
                    self.app.bind(
                        "<Configure>", self._on_app_configure, add="+")
                    self._app_cfg_bound = True
                except Exception:
                    pass
        except Exception:
            self._dim_overlay = None
        return self._dim_overlay

    def _on_app_configure(self, _event=None) -> None:
        ov = getattr(self, "_dim_overlay", None)
        try:
            if ov is not None and ov.winfo_ismapped():
                self._position_dim_overlay()
                ov.lift()
        except Exception:
            pass

    def _position_dim_overlay(self) -> bool:
        """Size the overlay to the visible chat right of the drawer.

        Returns False if the chat isn't laid out yet (can't size).
        """
        ov = getattr(self, "_dim_overlay", None)
        if ov is None:
            return False
        try:
            # NOTE: never call update_idletasks() here — this runs inside
            # <Configure> handlers, and forcing idle processing mid-resize
            # re-enters the event loop and crashes. winfo_* is already current
            # during a Configure.
            sf = self.second_frame
            x, y = sf.winfo_rootx(), sf.winfo_rooty()
            w, h = sf.winfo_width(), sf.winfo_height()
            # The drawer's ACTUAL (physical) width. _WIDTH is logical, but the
            # CTk drawer renders at _WIDTH * display-scaling, and winfo_* here
            # are physical px — using the logical _WIDTH makes the overlay start
            # INSIDE the drawer on a scaled display (e.g. Windows 125%), so it
            # covers the drawer's close buttons and steals their clicks.
            drawer_w = self._sidebar.winfo_width()
            if drawer_w <= 1:
                base = getattr(self._sidebar, "_WIDTH", 220)
                try:
                    base = int(round(
                        base * customtkinter.ScalingTracker
                        .get_widget_scaling(self._sidebar)))
                except Exception:
                    pass
                drawer_w = base
            ox = x + drawer_w
            ow = w - drawer_w
            if ow <= 1 or h <= 1:
                return False
            ov.geometry(f"{int(ow)}x{int(h)}+{int(ox)}+{int(y)}")
            return True
        except Exception:
            return False

    def _sync_drawer_geometry(self) -> None:
        """Size + place the drawer to fill the chat area below the header.

        CTk's place() refuses an absolute height (it must be set via the
        constructor / configure()), so we configure() the height and only pass
        x/y to place(). Width comes from the ChatSidebar constructor.
        """
        try:
            # winfo_height() is PHYSICAL px; CTk's configure(height=) multiplies
            # by widget scaling, so divide first or the drawer is stretched ~25%
            # too tall on a scaled display (Windows 125%/150%) and its bottom is
            # clipped off-window. _DRAWER_TOP is a logical offset, so scale it to
            # physical before subtracting. No-op on macOS (scaling == 1.0).
            try:
                s = customtkinter.ScalingTracker.get_widget_scaling(
                    self._sidebar)
            except Exception:
                s = 1.0
            h_phys = self.second_frame.winfo_height() - self._DRAWER_TOP * s
            self._sidebar.configure(height=max(1, int(round(h_phys / s))))
            self._sidebar.place(x=0, y=self._DRAWER_TOP)
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
        # Collapse the toggle bar back to a bare, transparent floating hamburger.
        tb = getattr(self, "_toggle_bar", None)
        if tb is not None:
            try:
                tb.configure(fg_color="transparent", width=56)
                tb.lift()
            except Exception:
                pass

    def _toggle_sidebar(self) -> None:
        # _show_sidebar / _hide_sidebar own _sidebar_visible now, so don't flip
        # it here too (that would double-toggle).
        if self._sidebar_visible:
            self._hide_sidebar()
        else:
            self._show_sidebar()

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

    def _available_width(self) -> int:
        try:
            self.chat_scroll.update_idletasks()
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
                   max_width=user_width(self._available_width()))
        return row

    def _add_assistant_bubble(
        self, is_dark: bool, md: str | None = None,
    ) -> AssistantBubble:
        row = self._make_row()
        ab = AssistantBubble(
            row, is_dark=is_dark,
            max_width=assistant_width(self._available_width()))
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
        # Re-entry guard. _on_resize itself triggers a cascade — set_width on
        # emoji bubbles enters _layout_emoji which calls self.configure() and
        # self.update_idletasks(); _update_scrollbar_visibility() toggles the
        # scrollbar's grid which changes the canvas's effective width. Either
        # path fires another <Configure> on chat_scroll, which re-enters
        # _on_resize before the current call has returned, eventually busting
        # Python's recursion limit.
        if getattr(self, "_in_on_resize", False):
            return
        self._in_on_resize = True
        try:
            avail = self._available_width()
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
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if not bbox:
                self._hide_scrollbar()
                return
            content_h = bbox[3] - bbox[1]
            visible_h = canvas.winfo_height()
            if content_h > visible_h:
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
