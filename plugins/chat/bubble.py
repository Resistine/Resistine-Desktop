"""Chat bubble widgets: BubbleRow, UserBubble, AssistantBubble.

Self-contained CTkFrame widgets packed into a CTkScrollableFrame to form
the chat conversation.

Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import sys
import tkinter as tk

import customtkinter

from plugins.chat.fonts import get_theme_colors

# ---------------------------------------------------------------------------
# Width constants
# ---------------------------------------------------------------------------

_ASST_RATIO, _ASST_MAX, _ASST_MIN = 0.72, 900, 200  # assistant bubble
_USER_RATIO, _USER_MAX, _USER_MIN = 0.75, 600, 200  # user bubble


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def user_width(available: int) -> int:
    """Compute user bubble width from available scroll-frame width."""
    return _clamp(int(available * _USER_RATIO), _USER_MIN, _USER_MAX)


def assistant_width(available: int) -> int:
    """Compute assistant bubble width from available scroll-frame width."""
    return _clamp(int(available * _ASST_RATIO), _ASST_MIN, _ASST_MAX)


# ---------------------------------------------------------------------------
# BubbleRow
# ---------------------------------------------------------------------------

class BubbleRow(customtkinter.CTkFrame):
    """Transparent full-width row that holds a single chat bubble."""

    def __init__(self, master: object, **kwargs: object) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)
        self.pack(fill="x", padx=0, pady=4)


# ---------------------------------------------------------------------------
# UserBubble
# ---------------------------------------------------------------------------

class UserBubble(customtkinter.CTkFrame):
    """Right-aligned bubble for user messages.

    Args:
        master: Parent widget (usually a BubbleRow).
        text: Plain-text user message.
        is_dark: Dark-mode flag.
        max_width: Maximum pixel width for text wrap.
    """

    _CORNER_RADIUS = 18
    _PAD_X = 18
    _PAD_Y = 11

    def __init__(
        self, master: object, text: str,
        is_dark: bool = False, max_width: int = 600,
        **kwargs: object,
    ) -> None:
        colors = get_theme_colors(is_dark)
        self._bg = colors["user_bubble_bg"]
        self._fg = colors["user_bubble_fg"]

        kwargs.setdefault("fg_color", self._bg)
        kwargs.setdefault("corner_radius", self._CORNER_RADIUS)
        super().__init__(master, **kwargs)
        self.pack(side="right", padx=(0, 12))

        self._text = text
        self._is_dark = is_dark
        self._max_width = max_width
        self._emoji_widget: tk.Text | None = None
        self._label: customtkinter.CTkLabel | None = None

        if self._needs_emoji_path(text):
            self._build_emoji(text, max_width)
        else:
            self._build_label(text, max_width)

    # -- construction helpers -----------------------------------------------

    @staticmethod
    def _needs_emoji_path(text: str) -> bool:
        """True when emoji image rendering is needed (Linux only)."""
        if sys.platform != "linux":
            return False
        try:
            from plugins.chat.markdown_bubble import _EMOJI_RE, _EMOJI_RENDER
            return bool(_EMOJI_RENDER and _EMOJI_RE and _EMOJI_RE.search(text))
        except ImportError:
            return False

    def _build_label(self, text: str, max_width: int) -> None:
        self._label = customtkinter.CTkLabel(
            self, text=text, fg_color="transparent",
            text_color=self._fg, wraplength=max_width,
            font=customtkinter.CTkFont(family="Inter", size=15),
            justify="left", anchor="w",
        )
        self._label.pack(padx=self._PAD_X, pady=self._PAD_Y)

    def _build_emoji(self, text: str, max_width: int) -> None:
        """Linux emoji path: tk.Text with inline emoji images."""
        from plugins.chat.markdown_bubble import MarkdownBubble, _EMOJI_RE

        _user_font = customtkinter.CTkFont(family="Inter", size=15)
        tw = tk.Text(
            self, bg=self._bg, fg=self._fg, font=_user_font,
            wrap="word", borderwidth=0, highlightthickness=0,
            padx=8, pady=1, cursor="xterm", insertwidth=0,
        )
        tw.configure(state="normal")

        emoji_photos: list[object] = []
        image_to_emoji: dict[str, str] = {}
        for i, part in enumerate(_EMOJI_RE.split(text)):
            if not part:
                continue
            if i % 2 == 1:
                for ch in MarkdownBubble._split_emoji_chars(part):
                    photo = MarkdownBubble._render_emoji(ch)
                    if photo:
                        emoji_photos.append(photo)
                        img_name = tw.image_create("end", image=photo, padx=1)
                        image_to_emoji[img_name] = ch
                    else:
                        tw.insert("end", ch)
            else:
                tw.insert("end", part)

        tw.configure(state="disabled")
        tags = tw.bindtags()
        tw.bindtags(tuple(t for t in tags if t != "Text"))
        tw._emoji_photos = emoji_photos  # type: ignore[attr-defined]
        tw._image_to_emoji = image_to_emoji  # type: ignore[attr-defined]

        self._emoji_widget = tw
        self._layout_emoji(tw, max_width)

    def _layout_emoji(self, tw: tk.Text, max_width: int) -> None:
        """Measure content and apply final dimensions for emoji text widget."""
        inset = 10
        padx_val = int(str(tw.cget("padx") or 0))

        tw.configure(wrap="none")
        try:
            result = tw.count("1.0", "end-1c", "xpixels")
            xpx = result[0] if isinstance(result, (list, tuple)) else result
            natural_w = int(xpx) + padx_val * 2
        except Exception:
            natural_w = max_width
        text_w = min(natural_w, max_width)

        tw.configure(wrap="word")
        tw.place(in_=self, x=inset, y=inset, width=text_w, height=500)
        self.configure(width=text_w + inset * 2, height=520)
        self.update_idletasks()

        try:
            result = tw.count("1.0", "end", "ypixels")
            val = result[0] if isinstance(result, (list, tuple)) else result
            content_h = int(val) + 4
        except Exception:
            import tkinter.font as tkfont
            content_h = tkfont.Font(font=("Inter", 15)).metrics("linespace") + 4

        tw.place_configure(height=content_h)
        self.configure(height=content_h + inset * 2)
        self.pack_propagate(False)

    # -- public API ---------------------------------------------------------

    def set_width(self, max_width: int) -> None:
        """Update wraplength on resize."""
        self._max_width = max_width
        if self._label is not None:
            self._label.configure(wraplength=max_width)
        elif self._emoji_widget is not None:
            self._layout_emoji(self._emoji_widget, max_width)


# ---------------------------------------------------------------------------
# AssistantBubble
# ---------------------------------------------------------------------------

class AssistantBubble(customtkinter.CTkFrame):
    """Left-aligned bubble for assistant responses.

    Two modes:
    - **Streaming:** ``set_streaming_text()`` updates a plain label.
    - **Finalized:** ``finalize_markdown()`` swaps the placeholder for
      a full MarkdownRenderer (or MarkdownBubble fallback).

    Args:
        master: Parent widget (usually a BubbleRow).
        is_dark: Dark-mode flag.
        max_width: Maximum pixel width for content.
    """

    _CORNER_RADIUS = 14

    def __init__(
        self, master: object,
        is_dark: bool = False, max_width: int = 700,
        **kwargs: object,
    ) -> None:
        colors = get_theme_colors(is_dark)
        self._bubble_bg = colors["bubble_bg"]
        self._bubble_fg = colors["bubble_fg"]

        kwargs.setdefault("fg_color", self._bubble_bg)
        kwargs.setdefault("corner_radius", self._CORNER_RADIUS)
        super().__init__(master, **kwargs)
        self.pack(side="left", fill="x", expand=True, padx=(12, 48))

        self._is_dark = is_dark
        self._max_width = max_width
        self._streaming_label: customtkinter.CTkLabel | None = None
        self._renderer: object | None = None
        self._thinking_label: customtkinter.CTkLabel | None = None
        self._thinking_step: int = 0
        self._thinking_after_id: str | None = None
        self._build_thinking_indicator()

    # -- thinking indicator -------------------------------------------------

    def _build_thinking_indicator(self) -> None:
        """Show a subtle animated indicator before the response arrives."""
        fg = "#9CA3AF" if self._is_dark else "#6B7280"
        self._thinking_label = customtkinter.CTkLabel(
            self, text="Thinking", fg_color="transparent",
            text_color=fg,
            font=customtkinter.CTkFont(
                family="Inter", size=14, slant="italic"),
            justify="left", anchor="w",
        )
        self._thinking_label.pack(
            fill="x", padx=16, pady=(10, 10), anchor="w")
        self._animate_thinking()

    def _animate_thinking(self) -> None:
        if self._thinking_label is None:
            return
        self._thinking_step = (self._thinking_step + 1) % 4
        self._thinking_label.configure(
            text="Thinking" + "." * self._thinking_step)
        self._thinking_after_id = self.after(
            400, self._animate_thinking)

    def _stop_thinking(self) -> None:
        if self._thinking_after_id is not None:
            self.after_cancel(self._thinking_after_id)
            self._thinking_after_id = None
        if self._thinking_label is not None:
            self._thinking_label.destroy()
            self._thinking_label = None

    # -- streaming ----------------------------------------------------------

    def _build_streaming_label(self) -> None:
        self._streaming_label = customtkinter.CTkLabel(
            self, text="", fg_color="transparent",
            text_color=self._bubble_fg, wraplength=self._max_width,
            font=customtkinter.CTkFont(family="Inter", size=15),
            justify="left", anchor="nw",
        )
        self._streaming_label.pack(fill="x", padx=16, pady=(6, 8), anchor="w")

    def set_streaming_text(self, text: str) -> None:
        """Update the streaming placeholder with accumulated text."""
        if self._thinking_label is not None:
            self._stop_thinking()
            self._build_streaming_label()
        if self._streaming_label is not None:
            self._streaming_label.configure(text=text)

    # -- finalize -----------------------------------------------------------

    def finalize_markdown(self, markdown_text: str) -> None:
        """Replace the streaming placeholder with rendered markdown.

        Tries MarkdownRenderer first; falls back to MarkdownBubble.
        """
        self._stop_thinking()
        if self._streaming_label is not None:
            self._streaming_label.destroy()
            self._streaming_label = None

        try:
            from plugins.chat.markdown_renderer import MarkdownRenderer
            self._renderer = MarkdownRenderer(
                self, markdown_text, self._is_dark, self._max_width,
            )
        except ImportError:
            from plugins.chat.markdown_bubble import MarkdownBubble
            self._renderer = MarkdownBubble(
                self, markdown_text, width=self._max_width,
            )
            self._renderer.pack(fill="x", expand=True)

    # -- public API ---------------------------------------------------------

    def set_width(self, max_width: int) -> None:
        """Update content width on resize."""
        self._max_width = max_width
        if self._streaming_label is not None:
            self._streaming_label.configure(wraplength=max_width)
        if self._renderer is not None and hasattr(self._renderer, "_update_width"):
            self._renderer._update_width(max_width)
