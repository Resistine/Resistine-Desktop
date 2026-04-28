"""Markdown-to-widget renderer for assistant chat bubbles.

Parses markdown line-by-line and packs CTkLabel widgets (prose) and block
widgets (code, tables, HRs) into a parent container.
"""
from __future__ import annotations

import re
import tkinter as tk

import customtkinter

from plugins.chat.fonts import get_fonts, get_theme_colors
from plugins.chat.markdown_utils import is_box_drawing, strip_inline_md
from plugins.chat.markdown_widgets import (
    CodeBlockWidget, HorizontalRule, SelectableLabel, TableWidget,
)

# Detect markdown formatting inside code fences (to unwrap non-code blocks).
_MD_IN_FENCE_RE = re.compile(
    r'\*\*\w[^*\n]*\*\*'
    r'|[\U0001F100-\U0001FAFF\U00002600-\U000027BF]'
)
_HR_RE = re.compile(r'^[-*_]{3,}\s*$')
_FENCE_RE = re.compile(r'^(\s*)```')
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)')
_BULLET_RE = re.compile(r'^(\s*)([-*+])\s(.*)')
_NUMBERED_RE = re.compile(r'^(\d+\.)\s(.*)')
_CHECKBOX_RE = re.compile(r'^-\s\[([ xX])\]\s(.*)')
_TABLE_SEP_RE = re.compile(r'^[\s\-:|]+$')
_ADMONITION_RE = re.compile(
    r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]')
_H_SPACING = {
    1: (8, 4), 2: (7, 3), 3: (6, 3),
    4: (5, 2), 5: (4, 2), 6: (4, 2),
}
_BOLD_WRAP_RE = re.compile(r'^\*\*(.+)\*\*[:\.\!\?]?\s*$')


# -- MarkdownRenderer ------------------------------------------------------
class MarkdownRenderer:
    """Parse markdown and pack CTkLabel / block widgets into *parent*."""

    def __init__(self, parent: tk.Widget, markdown_text: str,
                 is_dark: bool = False, max_width: int = 700,
                 selectable: bool = False) -> None:
        self._parent = parent
        self._is_dark = is_dark
        self._max_width = max_width
        self._selectable = selectable
        self._fonts = {}
        for key, tf in get_fonts(is_dark).items():
            kw = {"family": tf.cget("family"),
                  "size": tf.cget("size")}
            if tf.cget("weight") == "bold":
                kw["weight"] = "bold"
            if tf.cget("slant") == "italic":
                kw["slant"] = "italic"
            self._fonts[key] = customtkinter.CTkFont(**kw)
        self._colors = get_theme_colors(is_dark)
        self._prose: list[tuple[str, tuple[str, ...]]] = []
        self._labels: list[customtkinter.CTkLabel] = []
        self.render(markdown_text)

    # -- Main parser --------------------------------------------------------

    def render(self, text: str, _depth: int = 0) -> None:
        """Walk *text* line-by-line, flushing prose and inserting blocks."""
        lines, i = text.split("\n"), 0
        while i < len(lines):
            line, stripped = lines[i], lines[i].strip()
            if _FENCE_RE.match(stripped):
                i = self._parse_code_fence(lines, i, stripped, _depth)
                continue
            if is_box_drawing(stripped):
                i = self._parse_box_drawing(lines, i)
                continue
            if stripped.startswith("|"):
                i = self._parse_table_block(lines, i)
                continue
            if _HR_RE.match(stripped):
                self._flush_prose()
                HorizontalRule(
                    self._parent, is_dark=self._is_dark,
                ).pack(fill="x", padx=0, pady=(2, 2))
                i += 1
                continue
            if not stripped:
                self._prose.append(("\n", ()))
                i += 1
                continue
            if self._parse_inline(line, stripped):
                i += 1
                continue
            if stripped.startswith("> "):
                i = self._parse_blockquote(lines, i)
                continue
            self._prose.append((stripped, ("paragraph",)))
            self._prose.append(("\n", ()))
            i += 1
        self._flush_prose()

    def _parse_inline(self, line: str, stripped: str) -> bool:
        """Try to parse a single-line inline element. Return True if handled."""
        hm = _HEADING_RE.match(stripped)
        if hm:
            self._prose.append(
                (hm.group(2), (f"h{len(hm.group(1))}",)))
            self._prose.append(("\n", ()))
            return True
        cm = _CHECKBOX_RE.match(stripped)
        if cm:
            ico = "\u2611  " if cm.group(1) in ("x", "X") else "\u2610  "
            self._prose += [(ico, ("bullet",)),
                            (cm.group(2), ("bullet",)), ("\n", ())]
            return True
        bm = _BULLET_RE.match(line)
        if bm:
            pfx = "    " * (len(bm.group(1)) // 2) + "  \u2022  "
            self._prose += [(pfx, ("bullet",)),
                            (bm.group(3), ("bullet",)), ("\n", ())]
            return True
        nm = _NUMBERED_RE.match(stripped)
        if nm:
            self._prose += [
                (f"  {nm.group(1)}  ", ("numbered", "bold")),
                (nm.group(2), ("numbered",)), ("\n", ())]
            return True
        return False

    # -- Block parsers ---------------------------------------------------------

    def _parse_code_fence(self, lines: list[str], i: int,
                          stripped: str, _depth: int) -> int:
        """Parse a fenced code block starting at line *i*."""
        self._flush_prose()
        lang = stripped.lstrip("`").strip() or ""
        code_lines: list[str] = []
        i += 1
        while i < len(lines):
            if _FENCE_RE.match(lines[i].strip()):
                i += 1
                break
            code_lines.append(lines[i])
            i += 1
        content = "\n".join(code_lines)
        if ((not lang
             or lang.lower() in ("markdown", "md", "text"))
                and _depth < 2
                and _MD_IN_FENCE_RE.search(content)):
            self.render(content, _depth + 1)
        else:
            CodeBlockWidget(
                self._parent, content,
                language=lang, is_dark=self._is_dark,
            ).pack(fill="x", padx=0, pady=(4, 4))
        return i

    def _parse_box_drawing(self, lines: list[str], i: int) -> int:
        """Parse consecutive box-drawing lines into a code block."""
        self._flush_prose()
        box_lines: list[str] = []
        while i < len(lines) and is_box_drawing(lines[i].strip()):
            box_lines.append(lines[i])
            i += 1
        CodeBlockWidget(
            self._parent, "\n".join(box_lines),
            language="", is_dark=self._is_dark,
        ).pack(fill="x", padx=0, pady=(4, 4))
        return i

    def _parse_table_block(self, lines: list[str], i: int) -> int:
        """Parse a markdown table starting at line *i*."""
        self._flush_prose()
        table_lines: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            table_lines.append(lines[i].strip())
            i += 1
        hdrs, rows = self._parse_table(table_lines)
        if hdrs:
            TableWidget(
                self._parent, hdrs, rows, is_dark=self._is_dark,
            ).pack(fill="x", padx=0, pady=(4, 4))
        return i

    def _parse_blockquote(self, lines: list[str], i: int) -> int:
        """Parse a blockquote (with optional admonition) at *i*."""
        quote_lines: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("> "):
            quote_lines.append(lines[i].strip()[2:])
            i += 1
        adm = _ADMONITION_RE.match(
            quote_lines[0] if quote_lines else "")
        if adm:
            self._prose += [
                (f"  {adm.group(1)}  ", ("bold", "blockquote")),
                ("\n", ())]
            quote_lines = quote_lines[1:]
        for q in quote_lines:
            if q.strip():
                self._prose.append((q, ("blockquote",)))
            self._prose.append(("\n", ()))
        return i

    # -- Prose flushing (CTkLabel) ------------------------------------------

    def _flush_prose(self) -> None:
        """Pack accumulated prose as CTkLabel widgets."""
        if not self._prose or all(
                t.strip() == "" for t, _ in self._prose):
            self._prose.clear()
            return
        for parts in self._group_prose_lines():
            if not parts:
                continue
            raw_text = "".join(t for t, _ in parts)
            if not raw_text.strip():
                continue
            all_tags = {tag for _, tags in parts for tag in tags}
            self._pack_prose_label(raw_text, all_tags)
        self._prose.clear()

    def _group_prose_lines(self) -> list[list[tuple[str, tuple[str, ...]]]]:
        """Split prose buffer into per-line groups."""
        lines: list[list[tuple[str, tuple[str, ...]]]] = []
        current: list[tuple[str, tuple[str, ...]]] = []
        for text, tags in self._prose:
            if text == "\n":
                lines.append(current)
                current = []
            else:
                current.append((text, tags))
        if current:
            lines.append(current)
        return lines

    def _pack_prose_label(self, raw_text: str, all_tags: set[str]) -> None:
        """Create and pack a selectable label for one prose line."""
        display_text = strip_inline_md(raw_text)
        heading_tag = next(
            (t for t in all_tags
             if len(t) == 2 and t[0] == "h" and t[1].isdigit()),
            None)
        # Font
        if heading_tag:
            font = self._fonts[heading_tag]
        elif _BOLD_WRAP_RE.match(raw_text.strip()):
            font = self._fonts["bold"]
        else:
            font = self._fonts["body"]
        # Colour
        if heading_tag:
            fg = self._colors["heading"]
        elif "blockquote" in all_tags:
            fg = self._colors["blockquote_bar"]
        else:
            fg = self._colors["fg"]
        # Padding
        padx_left = 8
        if "bullet" in all_tags or "numbered" in all_tags:
            padx_left = 20
        elif "blockquote" in all_tags:
            padx_left = 16
        if heading_tag:
            level = int(heading_tag[1])
            top, bottom = _H_SPACING.get(level, (4, 2))
            pady = (top, bottom)
        else:
            pady = (1, 1)
        wraplength = max(100, self._max_width - padx_left - 8)
        if self._selectable:
            bg = self._colors["prose_bg"]
            lbl = SelectableLabel(
                self._parent, text=display_text, font=font,
                fg=fg, bg=bg, max_width=wraplength,
            )
        else:
            lbl = customtkinter.CTkLabel(
                self._parent, text=display_text, font=font,
                text_color=fg, fg_color="transparent",
                wraplength=wraplength, justify="left", anchor="w",
            )
        lbl.pack(fill="x", padx=(padx_left, 8), pady=pady)
        self._labels.append(lbl)

    # -- Resize -------------------------------------------------------------

    def _update_width(self, max_width: int) -> None:
        """Refit all labels after a resize."""
        self._max_width = max_width
        w = max(100, max_width - 28)
        for lbl in self._labels:
            try:
                if hasattr(lbl, "set_width"):
                    lbl.set_width(w)
                else:
                    lbl.configure(wraplength=w)
            except Exception:
                pass

    # -- Table parsing ------------------------------------------------------

    @staticmethod
    def _parse_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
        """Return (headers, rows) from raw markdown table lines."""
        data: list[list[str]] = []
        for ln in lines:
            inner = ln.strip("|").strip()
            if _TABLE_SEP_RE.match(inner):
                continue
            data.append([strip_inline_md(c.strip()) for c in inner.split("|")])
        return (data[0], data[1:]) if data else ([], [])
