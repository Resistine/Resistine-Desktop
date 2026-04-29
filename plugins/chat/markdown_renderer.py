"""Markdown-to-widget renderer for assistant chat bubbles.

Parses markdown line-by-line and renders into a single CTkTextbox with
styled text tags.  Block elements (code, tables, HRs) are embedded as
window widgets.  This allows continuous text selection across the entire
response.
"""
from __future__ import annotations

import re
import sys
import tkinter as tk

import customtkinter

from plugins.chat.fonts import get_fonts, get_theme_colors
from plugins.chat.markdown_utils import is_box_drawing, strip_inline_md
from plugins.chat.markdown_widgets import (
    CodeBlockWidget, HorizontalRule, TableWidget,
)

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
    1: (10, 6), 2: (8, 5), 3: (7, 4),
    4: (6, 3), 5: (5, 3), 6: (5, 3),
}
_BOLD_WRAP_RE = re.compile(r'^\*\*(.+)\*\*[:\.\!\?]?\s*$')


class MarkdownRenderer:
    """Parse markdown and render into a single CTkTextbox in *parent*."""

    def __init__(self, parent: tk.Widget, markdown_text: str,
                 is_dark: bool = False, max_width: int = 700) -> None:
        self._parent = parent
        self._is_dark = is_dark
        self._max_width = max_width
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
        self._first_line = True
        self._resize_timer = None
        self._tables: list[TableWidget] = []
        self._code_blocks: list[CodeBlockWidget] = []
        self._in_resize = False

        self._build_textbox()
        self._configure_tags()
        self.render(markdown_text)
        self.text_widget.configure(state="disabled")
        self._setup_scroll_redirect()
        self.text_widget.after(100, self._resize_to_fit)
        self.text_widget.after(400, self._resize_to_fit)

    def _build_textbox(self) -> None:
        """Create the single CTkTextbox that holds all content."""
        fg = self._colors["fg"]
        self.text_widget = customtkinter.CTkTextbox(
            self._parent, wrap="word", fg_color="transparent",
            text_color=fg,
            font=self._fonts["body"],
            border_width=0, corner_radius=0,
            activate_scrollbars=False,
        )
        self.text_widget.pack(fill="both", expand=True, padx=16,
                              pady=(2, 8))
        self._tw = self.text_widget._textbox
        self._tw.configure(padx=8, pady=4, wrap="word")

        sel_bg = "#264F78" if self._is_dark else "#B5D4F8"
        sel_fg = "#FFFFFF" if self._is_dark else "#000000"
        self._tw.configure(
            selectbackground=sel_bg, selectforeground=sel_fg,
            inactiveselectbackground=sel_bg,
            xscrollcommand=lambda *_: None,
        )
        self._parent.pack_propagate(False)

    def _configure_tags(self) -> None:
        """Set up text tags for headings, bullets, etc."""
        tw = self._tw
        colors = self._colors
        for level in range(1, 7):
            tag = f"h{level}"
            top, bottom = _H_SPACING.get(level, (4, 2))
            tw.tag_configure(
                tag, font=self._fonts[tag],
                foreground=colors["heading"],
                spacing1=top, spacing3=bottom,
            )
        for htag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            tw.tag_raise(htag)
        tw.tag_configure("bold", font=self._fonts["bold"])
        tw.tag_configure(
            "bullet", lmargin1=20, lmargin2=36,
            spacing1=2, spacing3=2,
        )
        tw.tag_configure(
            "numbered", lmargin1=20, lmargin2=36,
            spacing1=2, spacing3=2,
        )
        tw.tag_configure(
            "blockquote", lmargin1=16, lmargin2=16,
            foreground=colors["blockquote_bar"],
            spacing1=5, spacing3=5,
        )
        tw.tag_configure("paragraph", spacing1=3, spacing3=3)

    # -- Main parser --------------------------------------------------------

    def render(self, text: str, _depth: int = 0) -> None:
        """Walk *text* line-by-line, inserting styled text and blocks."""
        tw = self._tw
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
                self._insert_newline()
                hr = HorizontalRule(tw, is_dark=self._is_dark)
                tw.window_create("end", window=hr, padx=0, pady=2,
                                 stretch=1)
                self._first_line = False
                i += 1
                continue
            if not stripped:
                if not self._first_line:
                    tw.insert("end", "\n")
                i += 1
                continue
            if self._parse_inline(line, stripped):
                i += 1
                continue
            if stripped.startswith("> "):
                i = self._parse_blockquote(lines, i)
                continue
            self._insert_newline()
            tw.insert("end", strip_inline_md(stripped), ("paragraph",))
            self._first_line = False
            i += 1

    def _insert_newline(self) -> None:
        if not self._first_line:
            self._tw.insert("end", "\n")

    def _parse_inline(self, line: str, stripped: str) -> bool:
        tw = self._tw
        hm = _HEADING_RE.match(stripped)
        if hm:
            self._insert_newline()
            tag = f"h{len(hm.group(1))}"
            tw.insert("end", strip_inline_md(hm.group(2)), (tag,))
            self._first_line = False
            return True
        cm = _CHECKBOX_RE.match(stripped)
        if cm:
            self._insert_newline()
            ico = "\u2611  " if cm.group(1) in ("x", "X") else "\u2610  "
            tw.insert("end", ico + strip_inline_md(cm.group(2)),
                       ("bullet",))
            self._first_line = False
            return True
        bm = _BULLET_RE.match(line)
        if bm:
            self._insert_newline()
            pfx = "    " * (len(bm.group(1)) // 2) + "  \u2022  "
            tw.insert("end", pfx + strip_inline_md(bm.group(3)),
                       ("bullet",))
            self._first_line = False
            return True
        nm = _NUMBERED_RE.match(stripped)
        if nm:
            self._insert_newline()
            tw.insert("end", f"  {nm.group(1)}  ", ("numbered", "bold"))
            tw.insert("end", strip_inline_md(nm.group(2)), ("numbered",))
            self._first_line = False
            return True
        bw = _BOLD_WRAP_RE.match(stripped)
        if bw:
            self._insert_newline()
            tw.insert("end", strip_inline_md(stripped), ("bold",))
            self._first_line = False
            return True
        return False

    # -- Block parsers ------------------------------------------------------

    def _parse_code_fence(self, lines: list[str], i: int,
                          stripped: str, _depth: int) -> int:
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
            self._insert_newline()
            w = CodeBlockWidget(
                self._tw, content,
                language=lang, is_dark=self._is_dark,
            )
            self._tw.window_create("end", window=w, padx=0, pady=4,
                                   stretch=1)
            self._code_blocks.append(w)
            self._first_line = False
        return i

    def _parse_box_drawing(self, lines: list[str], i: int) -> int:
        box_lines: list[str] = []
        while i < len(lines) and is_box_drawing(lines[i].strip()):
            box_lines.append(lines[i])
            i += 1
        self._insert_newline()
        w = CodeBlockWidget(
            self._tw, "\n".join(box_lines),
            language="", is_dark=self._is_dark,
        )
        self._tw.window_create("end", window=w, padx=0, pady=4,
                               stretch=1)
        self._code_blocks.append(w)
        self._first_line = False
        return i

    def _parse_table_block(self, lines: list[str], i: int) -> int:
        table_lines: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            table_lines.append(lines[i].strip())
            i += 1
        hdrs, rows = self._parse_table(table_lines)
        if hdrs:
            self._insert_newline()
            w = TableWidget(
                self._tw, hdrs, rows, is_dark=self._is_dark,
            )
            self._tw.window_create("end", window=w, padx=0, pady=4,
                                   stretch=1)
            self._tables.append(w)
            self._first_line = False
        return i

    def _parse_blockquote(self, lines: list[str], i: int) -> int:
        quote_lines: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("> "):
            quote_lines.append(lines[i].strip()[2:])
            i += 1
        adm = _ADMONITION_RE.match(
            quote_lines[0] if quote_lines else "")
        if adm:
            self._insert_newline()
            self._tw.insert(
                "end", f"  {adm.group(1)}  ",
                ("bold", "blockquote"))
            self._first_line = False
            quote_lines = quote_lines[1:]
        for q in quote_lines:
            if q.strip():
                self._insert_newline()
                self._tw.insert(
                    "end", strip_inline_md(q), ("blockquote",))
                self._first_line = False
        return i

    # -- Scroll redirect ----------------------------------------------------

    def _setup_scroll_redirect(self) -> None:
        """Forward mousewheel from the textbox to the parent scroll frame."""
        tw = self._tw
        parent = self._parent
        while parent is not None:
            if isinstance(parent, customtkinter.CTkScrollableFrame):
                canvas = parent._parent_canvas

                def _forward(e, c=canvas):
                    try:
                        c.event_generate("<MouseWheel>", delta=e.delta)
                    except Exception:
                        pass
                    return "break"

                tw.bind("<MouseWheel>", _forward)
                return
            parent = getattr(parent, "master", None)

    # -- Resize -------------------------------------------------------------

    def _resize_to_fit(self) -> None:
        """Set the parent frame height to fit content."""
        if self._in_resize:
            return
        self._in_resize = True
        try:
            tw = self._tw
            tw.update_idletasks()

            try:
                tw_pady = int(str(tw.cget("pady") or 0))
            except (ValueError, tk.TclError):
                tw_pady = 0
            # tw pady + CTkTextbox pack pady (2+8) + extra buffer
            padding = tw_pady * 2 + 20

            h = None
            try:
                result = tw.count("1.0", "end", "ypixels")
                if result is not None:
                    val = (result[0] if isinstance(result, (list, tuple))
                           else result)
                    h = int(val) + padding
            except (tk.TclError, TypeError, ValueError):
                pass

            if h is None:
                info = tw.dlineinfo("end-1c")
                if info:
                    h = info[1] + info[3] + padding
                else:
                    return

            self._parent.configure(height=h)
            self.text_widget.configure(height=h)
            # Resize embedded widgets to textbox width
            try:
                tw_width = tw.winfo_width()
                if tw_width > 1:
                    padx = int(str(tw.cget("padx") or 0))
                    embed_w = tw_width - padx * 2
                    for tbl in self._tables:
                        tbl.configure(width=embed_w)
                        tbl._resize_to_width(embed_w)
                    for cb in self._code_blocks:
                        cb.configure(width=embed_w)
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self._in_resize = False

    def _update_width(self, max_width: int) -> None:
        """Refit after a resize."""
        self._max_width = max_width
        if self._resize_timer:
            self._parent.after_cancel(self._resize_timer)
        self._resize_timer = self._parent.after(
            50, self._resize_to_fit)

    # -- Table parsing ------------------------------------------------------

    @staticmethod
    def _parse_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
        data: list[list[str]] = []
        for ln in lines:
            inner = ln.strip("|").strip()
            if _TABLE_SEP_RE.match(inner):
                continue
            data.append([strip_inline_md(c.strip())
                         for c in inner.split("|")])
        return (data[0], data[1:]) if data else ([], [])
