"""Thin MarkdownBubble shim -- preserves public API, delegates to MarkdownRenderer.

Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import io
import re
import sys

import customtkinter

from utils.logger import logger

# ---------------------------------------------------------------------------
# Emoji constants -- Linux-only colour emoji rendering via cairosvg
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile(
    "(["
    "\U0001F100-\U0001FAFF"  # Enclosed Alphanumerics … Symbols Extended-A
    "\U00002600-\U000027BF"  # Misc Symbols, Dingbats
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "\U0000200D"             # Zero Width Joiner (for composite emoji)
    "\U000020E3"             # Combining Enclosing Keycap
    "]+)"
) if sys.platform == "linux" else None

_EMOJI_RENDER = False
if _EMOJI_RE is not None:
    try:
        import cairosvg as _emoji_cairosvg
        from PIL import Image as _emoji_Image, ImageTk as _emoji_ImageTk
        _EMOJI_RENDER = True
    except (ImportError, OSError):
        pass

# Box-drawing characters that indicate ASCII art diagrams
_BOX_CHARS = set("┌┐└┘├┤┬┴┼─│╭╮╯╰╱╲▲▼◄►═║╔╗╚╝╠╣╦╩╬")


# ---------------------------------------------------------------------------
# MarkdownBubble -- thin CTkFrame that delegates rendering
# ---------------------------------------------------------------------------

class MarkdownBubble(customtkinter.CTkFrame):
    """Renders markdown content inside a CTkFrame.

    Public API preserved for ``plugins.help.markdown_viewer`` and
    ``utils.emoji_entry``.  Internally delegates to ``MarkdownRenderer``
    from ``plugins.chat.markdown_renderer``.
    """

    # Shared cache for rendered emoji PhotoImages
    _emoji_cache: dict[str, object] = {}

    _EMOJI_FONTS = ["Noto Color Emoji", "Noto Sans Symbols 2", "Noto Sans"]

    def __init__(self, master, markdown_content: str, **kwargs):
        super().__init__(master, fg_color="transparent", corner_radius=0, **kwargs)
        self.markdown_content = markdown_content

        # Detect dark mode
        is_dark = self._detect_dark_mode()

        try:
            from plugins.chat.markdown_renderer import MarkdownRenderer
            self._renderer = MarkdownRenderer(
                self, markdown_content, is_dark=is_dark,
            )
        except Exception as exc:
            logger.warning(f"MarkdownRenderer unavailable, using fallback: {exc}")
            self._render_fallback()

    # ------------------------------------------------------------------
    # Dark-mode detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_dark_mode() -> bool:
        """Return True when the current appearance is dark."""
        mode = customtkinter.get_appearance_mode()
        if mode == "Dark":
            return True
        if mode == "Light":
            return False
        if sys.platform == "darwin":
            try:
                import subprocess
                res = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True, text=True,
                )
                return res.returncode == 0 and "Dark" in res.stdout
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # Fallback -- plain label when the renderer is missing
    # ------------------------------------------------------------------

    def _render_fallback(self) -> None:
        label = customtkinter.CTkLabel(
            self,
            text=self.markdown_content,
            anchor="w",
            justify="left",
            wraplength=600,
        )
        label.pack(fill="both", expand=True, padx=16, pady=12)

    # ------------------------------------------------------------------
    # Emoji rendering (static/class -- used by utils.emoji_entry)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_emoji_chars(text: str) -> list[str]:
        """Split a string of consecutive emoji into individual emoji.

        Handles ZWJ sequences (e.g. family emoji) and variation selectors
        as single units.
        """
        chunks: list[str] = []
        buf = ""
        for ch in text:
            if ch == "\u200D" or "\uFE00" <= ch <= "\uFE0F":
                # ZWJ or variation selector -- attach to previous
                buf += ch
            elif buf and buf[-1] == "\u200D":
                # Character after ZWJ -- part of the sequence
                buf += ch
            else:
                if buf:
                    chunks.append(buf)
                buf = ch
        if buf:
            chunks.append(buf)
        return chunks

    @classmethod
    def _render_emoji(cls, emoji_str: str, size: int = 20) -> object | None:
        """Rasterise an emoji string to a PhotoImage via cairosvg.

        Tries Noto Color Emoji first.  If the result is too narrow or
        empty (font lacks a proper color glyph), falls back to Noto Sans.
        """
        cache_key = f"{emoji_str}_{size}"
        if cache_key in cls._emoji_cache:
            return cls._emoji_cache[cache_key]

        canvas = size + 10
        pad = 5
        safe = emoji_str.replace("&", "&amp;").replace("<", "&lt;")

        for font_family in cls._EMOJI_FONTS:
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{canvas}" height="{canvas}">'
                f'<text x="{pad}" y="{int(size * 0.82) + pad}" '
                f'font-family="{font_family}" font-size="{size}">'
                f'{safe}</text></svg>'
            )
            try:
                png_data = _emoji_cairosvg.svg2png(
                    bytestring=svg.encode("utf-8"),
                )
                img = _emoji_Image.open(io.BytesIO(png_data))
                bbox = img.getbbox()
                if not bbox:
                    continue
                cropped = img.crop(bbox)
                if cls._is_tofu(cropped):
                    continue
                photo = _emoji_ImageTk.PhotoImage(cropped)
                cls._emoji_cache[cache_key] = photo
                return photo
            except Exception:
                continue
        return None

    @staticmethod
    def _is_tofu(img) -> bool:
        """Detect if a rendered glyph is a tofu rectangle (missing glyph).

        Tofu is a single-color unfilled rectangle -- nearly all visible
        pixels share one colour and they form a rectangular outline.
        """
        w, h = img.size
        if w < 4 or h < 4:
            return False
        colors: dict[tuple[int, int, int], int] = {}
        for x in range(w):
            for y in range(h):
                r, g, b, a = img.getpixel((x, y))
                if a < 20:
                    pass  # transparent
                else:
                    key = (r >> 4, g >> 4, b >> 4)
                    colors[key] = colors.get(key, 0) + 1
        # Tofu: one dominant colour, hollow interior
        if len(colors) > 3:
            return False  # real emoji have many colours
        # Check if the interior is mostly transparent (hollow rectangle)
        if w > 6 and h > 6:
            interior_transparent = 0
            interior_total = 0
            for x in range(3, w - 3):
                for y in range(3, h - 3):
                    interior_total += 1
                    if img.getpixel((x, y))[3] < 20:
                        interior_transparent += 1
            if interior_total > 0 and interior_transparent / interior_total > 0.7:
                return True
        return False

    # ------------------------------------------------------------------
    # Inline markdown helpers (used by markdown_renderer / widgets)
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_inline_md(text: str) -> str:
        """Strip inline markdown markers, returning plain text."""
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'~~(.+?)~~', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'\[(.+?)\]\([^)]+\)', r'\1', text)
        return text

    @classmethod
    def _is_box_drawing(cls, line: str) -> bool:
        """Return True if the line looks like an ASCII art / box diagram."""
        if not line:
            return False
        return bool(_BOX_CHARS.intersection(line))
