"""Chat UI construction mixin for the Chat plugin."""
from __future__ import annotations

import sys

import customtkinter

from plugins.chat.assistant_bubble import AssistantBubble
from plugins.chat.bubble import BubbleRow, UserBubble, assistant_width, user_width
from plugins.chat.fonts import RESISTINE_BLUE, _is_dark_mode, ui_family
from plugins.chat.sidebar import ChatSidebar
from plugins.chat.welcome_screen import ApiKeyMissingScreen, WelcomeScreen
from utils.emoji_entry import EmojiEntry


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

    def create_main_screen(self):
        is_dark = _is_dark_mode()
        self._ensure_session()

        self.second_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent")

        self._sidebar = ChatSidebar(
            self.second_frame,
            on_select=self._select_chat,
            on_new_chat=self._new_chat,
            on_delete=self._delete_chat,
            is_dark=is_dark)
        if self._sidebar_visible:
            self._sidebar.pack(side="left", fill="y")

        self._build_chat_area(is_dark)
        self._refresh_sidebar()
        return self.second_frame

    def _build_chat_area(self, is_dark: bool) -> None:
        self._chat_area = customtkinter.CTkFrame(
            self.second_frame, corner_radius=0, fg_color="transparent")
        self._chat_area.pack(side="left", fill="both", expand=True)
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
                # Windows blits the embedded canvas window on scroll and can
                # leave ghost "tracers" of the old text until the child widgets
                # repaint. Forcing a synchronous repaint right after each wheel
                # scroll clears them. Gated to Windows — macOS/Linux repaint
                # cleanly and need no nudge.
                canvas.bind(
                    "<MouseWheel>",
                    lambda _e: canvas.update_idletasks(),
                    add="+")
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
        bar.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.98, y=-14)
        bar.grid_columnconfigure(0, weight=1)
        self.chat_entry = EmojiEntry(
            bar, placeholder_text="Message Resistine AI...",
            corner_radius=20, border_width=0, height=44,
            font=customtkinter.CTkFont(family=ui_family(), size=18),
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

    def _toggle_sidebar(self) -> None:
        if self._sidebar_visible:
            self._sidebar.pack_forget()
        else:
            self._sidebar.pack(side="left", fill="y",
                               before=self._chat_area)
        self._sidebar_visible = not self._sidebar_visible

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
