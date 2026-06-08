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

from plugins.chat.fonts import _is_dark_mode
from plugins.chat.markdown_utils import is_box_drawing, strip_inline_md
from utils.logger import logger

# ---------------------------------------------------------------------------
# Emoji constants -- Linux-only colour emoji rendering via cairosvg
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile(
    # Keycap sequences: digit/#/* + optional VS16 + combining keycap.
    # Matched first so the ASCII base character is pulled into the emoji
    # chunk (e.g. "1️⃣" instead of "1" + lonely combiner).
    "([0-9#*]️?⃣|["
    "\U0001F000-\U0001FAFF"  # Mahjong, Domino, Playing Cards, ..., Symbols Extended-A
    "\U00002300-\U000023FF"  # Misc Technical (⌚ ⌛ ⌨ ⏏ ⏩-⏳ ⏸-⏺)
    "\U000024C2"             # Ⓜ
    "\U000025AA-\U000025FE"  # Geometric Shapes used as emoji (▪ ▫ ▶ ◀ ◻ ◼ ◽ ◾)
    "\U00002600-\U000027BF"  # Misc Symbols, Dingbats
    "\U00002934-\U00002935"  # ⤴ ⤵
    "\U00002B00-\U00002BFF"  # Misc Symbols and Arrows (⬅ ⬆ ⬇ ⬛ ⬜ ⭐ ⭕)
    "\U00003030"             # 〰
    "\U0000303D"             # 〽
    "\U00003297"             # ㊗
    "\U00003299"             # ㊙
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

# Shaped-emoji pipeline: HarfBuzz shapes the codepoint sequence into a
# glyph ID in Noto Color Emoji, blackrenderer paints the COLRv1 glyph,
# the resulting SVG goes through cairosvg -> PNG -> PhotoImage. This is
# the only path that renders ZWJ sequences, flags, skin tones, keycaps,
# etc. as their actual colour glyph instead of decomposing into separate
# codepoint glyphs. Falls back to the plain cairosvg path below if any
# dep or font is missing.
_SHAPED_RENDER = False
_hb_font = None
_br_font = None
_hb_extents = None
_NCE_PATH = None
if _EMOJI_RENDER:
    try:
        import logging as _logging
        import subprocess as _subprocess
        import uharfbuzz as _uharfbuzz
        from blackrenderer.font import BlackRendererFont as _BlackRendererFont
        from blackrenderer.backends.svg import SVGSurface as _SVGSurface
        # blackrenderer's SVG backend logs a warning on each new canvas
        # about "unbounded draw operations" (COLRv1 paint graphs with
        # canvas-spanning gradients). The visual output is still correct,
        # so silence that specific logger.
        _logging.getLogger("blackrenderer.backends.svg").setLevel(
            _logging.ERROR)
        _NCE_PATH = _subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Color Emoji"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        if _NCE_PATH:
            with open(_NCE_PATH, "rb") as _f:
                _font_bytes = _f.read()
            _hb_face = _uharfbuzz.Face(_font_bytes)
            _hb_font = _uharfbuzz.Font(_hb_face)
            _hb_extents = _hb_font.get_font_extents("ltr")
            _br_font = _BlackRendererFont(_NCE_PATH)
            _SHAPED_RENDER = True
    except (ImportError, OSError, FileNotFoundError, Exception):
        _SHAPED_RENDER = False


def _render_shaped_emoji(emoji_str: str, size: int):
    """Shape ``emoji_str`` with HarfBuzz, paint the COLRv1 glyph(s), and
    return a cropped RGBA ``PIL.Image`` or ``None`` on failure."""
    if not _SHAPED_RENDER:
        return None
    try:
        import tempfile
        import os
        buf = _uharfbuzz.Buffer()
        buf.add_str(emoji_str)
        buf.guess_segment_properties()
        _uharfbuzz.shape(_hb_font, buf)
        glyphs = list(zip(buf.glyph_infos, buf.glyph_positions))
        if not glyphs or all(info.codepoint == 0 for info, _ in glyphs):
            return None
        upem = _hb_face.upem
        scale = size / upem
        pad = max(2, int(size * 0.15))
        total_advance = sum(pos.x_advance for _, pos in glyphs)
        width_px = int(total_advance * scale) + pad * 2
        glyph_h = int((_hb_extents.ascender - _hb_extents.descender) * scale)
        height_px = glyph_h + pad * 2
        baseline_user_y = pad + int(-_hb_extents.descender * scale)
        surface = _SVGSurface()
        with surface.canvas((0, 0, width_px, height_px)) as canvas:
            x = pad
            for info, pos in glyphs:
                gid = info.codepoint
                if gid == 0 or gid >= len(_br_font.glyphNames):
                    x += int(pos.x_advance * scale)
                    continue
                name = _br_font.glyphNames[gid]
                with canvas.savedState():
                    canvas.translate(
                        x + pos.x_offset * scale,
                        baseline_user_y + pos.y_offset * scale,
                    )
                    canvas.scale(scale, scale)
                    _br_font.drawGlyph(name, canvas)
                x += int(pos.x_advance * scale)
        fd, tmp = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            surface.saveImage(tmp)
            with open(tmp, "rb") as f:
                svg_data = f.read()
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        png = _emoji_cairosvg.svg2png(bytestring=svg_data)
        img = _emoji_Image.open(io.BytesIO(png)).convert("RGBA")
        crop = img.getbbox()
        return img.crop(crop) if crop else img
    except Exception as exc:
        logger.warning(f"Shaped emoji render failed for {emoji_str!r}: {exc}")
        return None


def attach_emoji_copy(tw, image_to_emoji: dict) -> None:
    """Bind ``<<Copy>>`` so a selection yields complete text.

    By default ``tk.Text`` skips embedded items when copying, so a
    selection produces text with gaps. We intercept the copy event, walk
    the selection via ``tw.dump``, and fill in each embed: inline emoji
    images become their codepoint (from ``image_to_emoji``), and embedded
    table / code-block windows contribute their text content — so a drag
    across the whole response copies the tables and code too.
    """
    import tkinter as _tk

    def _on_copy(_event=None, w=tw, m=image_to_emoji):
        try:
            start = w.index("sel.first")
            end = w.index("sel.last")
        except _tk.TclError:
            return None
        parts = []
        for kind, val, _idx in w.dump(start, end):
            if kind == "text":
                parts.append(val)
            elif kind == "image":
                parts.append(m.get(val, ""))
            elif kind == "window":
                # Embedded table / code block — Tk omits these on copy, so
                # pull their text so the selection includes them.
                try:
                    embed = w.nametowidget(val)
                except Exception:
                    embed = None
                emb_txt = (getattr(embed, "_copy_text", None)
                           or getattr(embed, "_code_text", None))
                if emb_txt:
                    parts.append(emb_txt)
        if parts:
            w.clipboard_clear()
            w.clipboard_append("".join(parts))
        return "break"

    tw.bind("<<Copy>>", _on_copy)

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

        is_dark = self._detect_dark_mode()
        try:
            from plugins.chat.markdown_renderer import MarkdownRenderer
            self._renderer = MarkdownRenderer(
                self, markdown_content, is_dark=is_dark,
            )
        except Exception as exc:
            logger.warning(
                f"MarkdownRenderer failed, using fallback: {exc}")
            self._render_fallback()

    # ------------------------------------------------------------------
    # Dark-mode detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_dark_mode() -> bool:
        """Return True when the current appearance is dark."""
        return _is_dark_mode()

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
            if (ch == "\u200D" or "\uFE00" <= ch <= "\uFE0F"
                    or ch == "\u20E3"):
                # ZWJ, variation selector, or combining enclosing keycap
                # -- attach to previous
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
        """Rasterise an emoji string to a PhotoImage.

        Primary path: HarfBuzz shapes the codepoint sequence into a glyph
        ID in Noto Color Emoji, blackrenderer paints the COLRv1 glyph.
        Handles ZWJ sequences, flags, skin tones, keycaps, etc.

        Fallback: cairosvg's toy-text renderer with Noto Color Emoji ->
        Noto Sans Symbols 2 -> Noto Sans. Works for single-codepoint
        emojis where shaping isn't required.
        """
        cache_key = f"{emoji_str}_{size}"
        if cache_key in cls._emoji_cache:
            return cls._emoji_cache[cache_key]

        shaped = _render_shaped_emoji(emoji_str, size)
        if shaped is not None:
            photo = _emoji_ImageTk.PhotoImage(shaped)
            cls._emoji_cache[cache_key] = photo
            return photo

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
        return strip_inline_md(text)

    @staticmethod
    def _is_box_drawing(line: str) -> bool:
        """Return True if the line looks like ASCII art / box diagram."""
        return is_box_drawing(line)
