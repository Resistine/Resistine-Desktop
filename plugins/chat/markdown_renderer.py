"""Markdown-to-widget renderer for assistant chat bubbles.

Parses markdown line-by-line and packs CTkLabel widgets (prose) and block
widgets (code, tables, HRs) into a parent container.

Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""
from __future__ import annotations

import re
import tkinter as tk
import webbrowser

import customtkinter

from plugins.chat.fonts import get_fonts, get_theme_colors
from plugins.chat.markdown_widgets import CodeBlockWidget, HorizontalRule, TableWidget
from utils.logger import logger

# -- Module-level exports (unit tests depend on these) ----------------------
_BOX_CHARS = frozenset("┌┐└┘├┤┬┴┼─│╭╮╯╰╱╲▲▼◄►═║╔╗╚╝╠╣╦╩╬")


def _is_box_drawing(line: str) -> bool:
    """Return True if *line* looks like an ASCII art / box diagram."""
    return bool(line and _BOX_CHARS.intersection(line))


def _strip_inline_md(text: str) -> str:
    """Strip inline markdown markers, returning plain text."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\([^)]+\)', r'\1', text)
    return text


# Inline formatting regex -- order matters (bold+italic > bold > italic).
_INLINE_RE = re.compile(
    r'(\*\*\*(?:(?!\*\*\*).)+?\*\*\*'  # ***bold italic***
    r'|\*\*(?:(?!\*\*).)+?\*\*'         # **bold**
    r'|~~(?:(?!~~).)+?~~'               # ~~strikethrough~~
    r'|`(?:(?!`).)+?`'                  # `code`
    r'|\*(?:(?!\*).)+?\*'               # *italic*
    r'|\[(?:(?!\]).)+?\]\([^)]+\)'      # [text](url)
    r')'
)

# Detect markdown formatting inside code fences (to unwrap non-code blocks).
_MD_IN_FENCE_RE = re.compile(
    r'\*\*\w[^*\n]*\*\*'                             # **bold** pattern
    r'|[\U0001F100-\U0001FAFF\U00002600-\U000027BF]'  # emoji characters
)
_URL_RE = re.compile(
    r'(https?://[^\s<>"{}|\\^`\[\]]+|www\.[^\s<>"{}|\\^`\[\]]+)'
)
_HR_RE = re.compile(r'^[-*_]{3,}\s*$')
_FENCE_RE = re.compile(r'^(\s*)```')
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)')
_BULLET_RE = re.compile(r'^(\s*)([-*+])\s(.*)')
_NUMBERED_RE = re.compile(r'^(\d+\.)\s(.*)')
_CHECKBOX_RE = re.compile(r'^-\s\[([ xX])\]\s(.*)')
_TABLE_SEP_RE = re.compile(r'^[\s\-:|]+$')
_ADMONITION_RE = re.compile(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]')
_H_SPACING = {1: (8, 4), 2: (7, 3), 3: (6, 3), 4: (5, 2), 5: (4, 2), 6: (4, 2)}
_BOLD_WRAP_RE = re.compile(r'^\*\*(.+)\*\*[:\.\!\?]?\s*$')


def _open_url(url: str) -> None:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        webbrowser.open(url)
    except Exception as exc:
        logger.warning(f"Failed to open URL {url}: {exc}")


# -- MarkdownRenderer ------------------------------------------------------
class MarkdownRenderer:
    """Parse markdown and pack CTkLabel / block widgets into *parent*."""

    def __init__(self, parent: tk.Widget, markdown_text: str,
                 is_dark: bool = False, max_width: int = 700) -> None:
        self._parent = parent
        self._is_dark = is_dark
        self._max_width = max_width
        # Convert tkFont.Font → CTkFont for use with CTkLabel
        self._fonts = {}
        for key, tf in get_fonts(is_dark).items():
            kw = {"family": tf.cget("family"), "size": tf.cget("size")}
            if tf.cget("weight") == "bold":
                kw["weight"] = "bold"
            if tf.cget("slant") == "italic":
                kw["slant"] = "italic"
            self._fonts[key] = customtkinter.CTkFont(**kw)
        self._colors = get_theme_colors(is_dark)
        self._prose: list[tuple[str, tuple[str, ...]]] = []
        self._labels: list[customtkinter.CTkLabel] = []
        self.render(markdown_text)

    def render(self, text: str, _depth: int = 0) -> None:  # noqa: C901
        """Walk *text* line-by-line, flush prose runs, insert block widgets."""
        lines, i = text.split("\n"), 0
        while i < len(lines):
            line, stripped = lines[i], lines[i].strip()
            # Code fences
            if _FENCE_RE.match(stripped):
                self._flush_prose()
                lang = stripped.lstrip("`").strip() or ""
                cl: list[str] = []
                i += 1
                while i < len(lines):
                    if _FENCE_RE.match(lines[i].strip()): i += 1; break
                    cl.append(lines[i]); i += 1
                content = "\n".join(cl)
                # Unlabeled fence whose content is markdown → re-parse
                if (not lang or lang.lower() in ("markdown", "md", "text")) \
                        and _depth < 2 and _MD_IN_FENCE_RE.search(content):
                    self.render(content, _depth + 1)
                    continue
                CodeBlockWidget(self._parent, content,
                                language=lang, is_dark=self._is_dark
                                ).pack(fill="x", padx=0, pady=(4, 4))
                continue
            # Box-drawing art -> code block
            if _is_box_drawing(stripped):
                self._flush_prose()
                bx: list[str] = []
                while i < len(lines) and _is_box_drawing(lines[i].strip()):
                    bx.append(lines[i]); i += 1
                CodeBlockWidget(self._parent, "\n".join(bx),
                                language="", is_dark=self._is_dark
                                ).pack(fill="x", padx=0, pady=(4, 4))
                continue
            # Table
            if stripped.startswith("|"):
                self._flush_prose()
                tl: list[str] = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    tl.append(lines[i].strip()); i += 1
                hdrs, rows = self._parse_table(tl)
                if hdrs:
                    TableWidget(self._parent, hdrs, rows,
                                is_dark=self._is_dark
                                ).pack(fill="x", padx=0, pady=(4, 4))
                continue
            # Horizontal rule
            if _HR_RE.match(stripped):
                self._flush_prose()
                HorizontalRule(self._parent, is_dark=self._is_dark
                               ).pack(fill="x", padx=0, pady=(2, 2))
                i += 1; continue
            # Empty line
            if not stripped:
                self._prose.append(("\n", ())); i += 1; continue
            # Headings
            hm = _HEADING_RE.match(stripped)
            if hm:
                self._prose.append((hm.group(2), (f"h{len(hm.group(1))}",)))
                self._prose.append(("\n", ())); i += 1; continue
            # Checkbox list
            cm = _CHECKBOX_RE.match(stripped)
            if cm:
                ico = "\u2611  " if cm.group(1) in ("x", "X") else "\u2610  "
                self._prose += [(ico, ("bullet",)), (cm.group(2), ("bullet",)),
                                ("\n", ())]
                i += 1; continue
            # Bullet list
            bm = _BULLET_RE.match(line)
            if bm:
                pfx = "    " * (len(bm.group(1)) // 2) + "  \u2022  "
                self._prose += [(pfx, ("bullet",)), (bm.group(3), ("bullet",)),
                                ("\n", ())]
                i += 1; continue
            # Numbered list
            nm = _NUMBERED_RE.match(stripped)
            if nm:
                self._prose += [(f"  {nm.group(1)}  ", ("numbered", "bold")),
                                (nm.group(2), ("numbered",)), ("\n", ())]
                i += 1; continue
            # Blockquote
            if stripped.startswith("> "):
                ql: list[str] = []
                while i < len(lines) and lines[i].strip().startswith("> "):
                    ql.append(lines[i].strip()[2:]); i += 1
                adm = _ADMONITION_RE.match(ql[0] if ql else "")
                if adm:
                    self._prose += [(f"  {adm.group(1)}  ",
                                     ("bold", "blockquote")), ("\n", ())]
                    ql = ql[1:]
                for q in ql:
                    if q.strip():
                        self._prose.append((q, ("blockquote",)))
                    self._prose.append(("\n", ()))
                continue
            # Paragraph
            self._prose.append((stripped, ("paragraph",)))
            self._prose.append(("\n", ())); i += 1
        self._flush_prose()

    # -- Prose flushing (CTkLabel) ------------------------------------------
    def _flush_prose(self) -> None:
        """Pack accumulated prose as CTkLabel widgets."""
        if not self._prose or all(t.strip() == "" for t, _ in self._prose):
            self._prose.clear()
            return

        # Group into lines (split at newline markers)
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

        for parts in lines:
            if not parts:
                continue

            raw_text = "".join(t for t, _ in parts)
            if not raw_text.strip():
                continue

            all_tags: set[str] = set()
            for _, tags in parts:
                all_tags.update(tags)

            display_text = _strip_inline_md(raw_text)

            # Determine heading tag (highest priority for font)
            heading_tag = None
            for tag in all_tags:
                if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
                    heading_tag = tag
                    break

            # Choose font
            if heading_tag:
                font = self._fonts[heading_tag]
            elif _BOLD_WRAP_RE.match(raw_text.strip()):
                font = self._fonts["bold"]
            else:
                font = self._fonts["body"]

            # Text colour
            if heading_tag:
                fg = self._colors["heading"]
            elif "blockquote" in all_tags:
                fg = self._colors["blockquote_bar"]
            else:
                fg = self._colors["fg"]

            # Horizontal padding (indentation)
            padx_left = 8
            if "bullet" in all_tags or "numbered" in all_tags:
                padx_left = 20
            elif "blockquote" in all_tags:
                padx_left = 16

            # Vertical spacing
            if heading_tag:
                level = int(heading_tag[1])
                top, bottom = _H_SPACING.get(level, (4, 2))
                pady = (top, bottom)
            else:
                pady = (1, 1)

            wraplength = max(100, self._max_width - padx_left - 8)

            lbl = customtkinter.CTkLabel(
                self._parent, text=display_text, font=font,
                text_color=fg, fg_color="transparent",
                wraplength=wraplength, justify="left", anchor="w",
            )
            lbl.pack(fill="x", padx=(padx_left, 8), pady=pady)
            self._labels.append(lbl)

        self._prose.clear()

    # -- Resize -------------------------------------------------------------
    def _update_width(self, max_width: int) -> None:
        """Refit all labels after a resize."""
        self._max_width = max_width
        for lbl in self._labels:
            try:
                lbl.configure(wraplength=max(100, max_width - 28))
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
            data.append([_strip_inline_md(c.strip()) for c in inner.split("|")])
        return (data[0], data[1:]) if data else ([], [])
