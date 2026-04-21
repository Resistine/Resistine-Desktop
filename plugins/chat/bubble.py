"""Chat bubble widgets: BubbleRow and UserBubble.

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

from plugins.chat.assistant_bubble import AssistantBubble  # noqa: F401
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
            from plugins.chat.markdown_bubble import (
                _EMOJI_RE, _EMOJI_RENDER,
            )
            return bool(
                _EMOJI_RENDER and _EMOJI_RE and _EMOJI_RE.search(text))
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
                        img_name = tw.image_create(
                            "end", image=photo, padx=1)
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
        """Measure and apply final dimensions for emoji text widget."""
        inset = 10
        padx_val = int(str(tw.cget("padx") or 0))

        tw.configure(wrap="none")
        try:
            result = tw.count("1.0", "end-1c", "xpixels")
            xpx = (result[0] if isinstance(result, (list, tuple))
                   else result)
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
            val = (result[0] if isinstance(result, (list, tuple))
                   else result)
            content_h = int(val) + 4
        except Exception:
            import tkinter.font as tkfont
            content_h = (
                tkfont.Font(font=("Inter", 15)).metrics("linespace") + 4
            )

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
