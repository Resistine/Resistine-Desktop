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
from plugins.chat.markdown_bubble import (
    _EMOJI_RE, _EMOJI_RENDER, MarkdownBubble, attach_emoji_copy,
)
from plugins.chat.markdown_utils import is_box_drawing, strip_inline_md
from plugins.chat.markdown_widgets import (
    CodeBlockWidget, HorizontalRule, TableWidget,
)

_MD_IN_FENCE_RE = re.compile(
    r'\*\*\w[^*\n]*\*\*'
    r'|[\U0001F100-\U0001FAFF\U00002600-\U000027BF]'
)
_HR_RE = re.compile(r'^[-*_]{3,}\s*$')
# ASCII rule / table border made of +, -, = (no pipes): e.g. +--------+ or
# ====. Used both as a standalone divider and as the top/middle/bottom border
# the model sometimes draws around a markdown table.
_ASCII_RULE_RE = re.compile(r'^[\s+=]*[-=]{3,}[\s+=\-]*$')
_FENCE_RE = re.compile(r'^(\s*)```')
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)')
_BULLET_RE = re.compile(r'^(\s*)([-*+])\s(.*)')
_NUMBERED_RE = re.compile(r'^(\d+\.)\s(.*)')
_CHECKBOX_RE = re.compile(r'^-\s\[([ xX])\]\s(.*)')
_TABLE_SEP_RE = re.compile(r'^[\s\-:|+]+$')


def _fence_has_md_table(content: str) -> bool:
    """True if *content* contains a markdown table — a row starting with '|'
    immediately followed by a separator row (|---|---|, dashes required).

    Used to recover a markdown table the model wrongly wrapped in a
    ```plaintext / ```text fence (it would otherwise show as raw '| **x** |'
    monospace). Terminal/data dumps without a separator row are NOT matched,
    so genuine code blocks stay code blocks.
    """
    rows = content.split("\n")
    for k in range(len(rows) - 1):
        nxt = rows[k + 1]
        if (rows[k].strip().startswith("|")
                and "-" in nxt
                and _TABLE_SEP_RE.match(nxt.strip().strip("|").strip())):
            return True
    return False
_ADMONITION_RE = re.compile(
    r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]')
_H_SPACING = {
    1: (10, 6), 2: (8, 5), 3: (7, 4),
    4: (6, 3), 5: (5, 3), 6: (5, 3),
}
_BOLD_WRAP_RE = re.compile(r'^\*\*(.+)\*\*[:\.\!\?]?\s*$')


def _logical_px(widget, px: int) -> int:
    """Convert a PHYSICAL-pixel size to the LOGICAL units a CTk widget's
    ``configure(width=/height=)`` expects.

    CTk multiplies configure() values by the display scaling. Our measurements
    come from raw tk widgets (``winfo_*`` / ``count("ypixels")``) in physical
    pixels, so passing them straight to a CTk widget scales them a SECOND time
    (e.g. 1.25x too big on a Windows 125% display) — which inflated the bubble
    height (the gap) and the table frame. Returns ``px`` unchanged at 100%.
    """
    try:
        s = customtkinter.ScalingTracker.get_widget_scaling(widget)
        return int(round(px / s)) if s else px
    except Exception:
        return px


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
        # Convergence state for _resize_to_fit. The reflow re-fires itself via
        # the embedded widgets' <Configure> bindings; these let it settle to a
        # fixed point (skip identical writes) and ignore the echo of its own
        # geometry changes, stopping the indefinite wider/narrower oscillation.
        self._suppress_embed_resize = False
        self._applied_parent_h = None
        # Last textbox width seen by _on_textbox_configure, so a pure-text
        # bubble re-measures its (width-dependent) height whenever the textbox
        # width settles — without that, a height measured while the textbox was
        # transiently narrow (over-wrapped) would be frozen forever.
        self._tb_last_w = None
        # Linux-only colour-emoji image rendering. Hold strong refs to
        # PhotoImages so Tk doesn't GC them, and remember the codepoint
        # behind each embedded image so copy/paste yields real emoji.
        self._emoji_photos: list[object] = []
        self._image_to_emoji: dict[str, str] = {}
        self._emoji_copy_bound = False

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
            xscrollcommand=self._pin_xview,
        )
        # The textbox should never xview-scroll: the only legitimate
        # horizontal content (wide tables, fenced code) carries its own
        # scrollbar. Block middle-click scan (Tk's drag-pan) outright,
        # and block trackpad horizontal swipes (Shift-wheel). The
        # ``xscrollcommand`` callback catches the remaining path
        # (drag-select past the edge calls ``$w see``, which fires
        # xscrollcommand before the redraw, so snapping there is
        # visually clean).
        for seq in ("<ButtonPress-2>", "<B2-Motion>",
                    "<ButtonRelease-2>", "<Shift-MouseWheel>",
                    "<Shift-Button-4>", "<Shift-Button-5>"):
            self._tw.bind(seq, lambda _e: "break")
        self._parent.pack_propagate(False)
        # A pure-text bubble (no embedded code/table) has NO <Configure>-driven
        # refit — those bindings live only on embedded widgets. Its only refits
        # are the fixed after(100)/after(400) timers, so if the textbox width
        # has not settled by 400ms the over-wrapped (too-tall) ypixels
        # measurement is frozen forever, leaving a large empty band below the
        # text. Bind a refit to the textbox's OWN <Configure> so a width settle
        # always re-measures, on every path (stream-finalize and restore alike).
        self.text_widget.bind(
            "<Configure>", self._on_textbox_configure, add="+")

    def _on_textbox_configure(self, event=None) -> None:
        """Refit when the textbox WIDTH changes; ignore height echoes.

        Reuses the same convergence guards as _on_embed_resize so it can never
        reintroduce the table reflow oscillation: bail while a resize is in
        flight, react to WIDTH changes only, and debounce. _resize_to_fit's
        height write stays gated on a settled width, so once width and height
        settle this mutates nothing and the timer stops.
        """
        if self._in_resize or self._suppress_embed_resize:
            return
        w = getattr(event, "width", None)
        if w is not None and w == self._tb_last_w:
            return
        self._tb_last_w = w
        if self._resize_timer:
            try:
                self._parent.after_cancel(self._resize_timer)
            except Exception:
                pass
        self._resize_timer = self._parent.after(80, self._resize_to_fit)

    def _pin_xview(self, first: str = "0.0", _last: str = "1.0") -> None:
        """Snap textbox xview back to 0 if anything shifts it."""
        try:
            if float(first) > 0.0:
                self._tw.xview_moveto(0.0)
        except (ValueError, tk.TclError):
            pass

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
            if _ASCII_RULE_RE.match(stripped):
                # A +-----+ ASCII border. If a |-row follows (skipping further
                # borders/blanks) it's the top of a model-drawn table -> parse
                # the table (the collector absorbs the borders). Otherwise it
                # is just a divider -> render as a horizontal rule.
                j = i
                while j < len(lines) and (
                        not lines[j].strip()
                        or _ASCII_RULE_RE.match(lines[j].strip())):
                    j += 1
                if j < len(lines) and lines[j].strip().startswith("|"):
                    i = self._parse_table_block(lines, i)
                    continue
                self._insert_newline()
                hr = HorizontalRule(tw, is_dark=self._is_dark)
                tw.window_create("end", window=hr, padx=0, pady=2,
                                 stretch=1)
                self._first_line = False
                i += 1
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
            self._insert(strip_inline_md(stripped), ("paragraph",))
            self._first_line = False
            i += 1

    def _insert_newline(self) -> None:
        if not self._first_line:
            self._tw.insert("end", "\n")

    def _insert(self, text: str, tags: tuple = ()) -> None:
        """Insert *text* into the textbox, rendering emoji as images on Linux.

        Falls back to a plain ``insert`` on macOS/Windows or when no emoji
        codepoints are present.
        """
        tw = self._tw
        if (not _EMOJI_RENDER or _EMOJI_RE is None
                or not _EMOJI_RE.search(text)):
            tw.insert("end", text, tags)
            return
        for i, part in enumerate(_EMOJI_RE.split(text)):
            if not part:
                continue
            if i % 2 == 1:
                for ch in MarkdownBubble._split_emoji_chars(part):
                    photo = MarkdownBubble._render_emoji(ch)
                    if photo:
                        self._emoji_photos.append(photo)
                        img_name = tw.image_create(
                            "end", image=photo, padx=1)
                        self._image_to_emoji[img_name] = ch
                    else:
                        tw.insert("end", ch, tags)
            else:
                tw.insert("end", part, tags)
        if not self._emoji_copy_bound:
            attach_emoji_copy(tw, self._image_to_emoji)
            self._emoji_copy_bound = True

    def _parse_inline(self, line: str, stripped: str) -> bool:
        tw = self._tw
        hm = _HEADING_RE.match(stripped)
        if hm:
            self._insert_newline()
            tag = f"h{len(hm.group(1))}"
            self._insert(strip_inline_md(hm.group(2)), (tag,))
            self._first_line = False
            return True
        cm = _CHECKBOX_RE.match(stripped)
        if cm:
            self._insert_newline()
            ico = "\u2611  " if cm.group(1) in ("x", "X") else "\u2610  "
            tw.insert("end", ico, ("bullet",))
            self._insert(strip_inline_md(cm.group(2)), ("bullet",))
            self._first_line = False
            return True
        bm = _BULLET_RE.match(line)
        if bm:
            self._insert_newline()
            pfx = "    " * (len(bm.group(1)) // 2) + "  \u2022  "
            tw.insert("end", pfx, ("bullet",))
            self._insert(strip_inline_md(bm.group(3)), ("bullet",))
            self._first_line = False
            return True
        nm = _NUMBERED_RE.match(stripped)
        if nm:
            self._insert_newline()
            tw.insert("end", f"  {nm.group(1)}  ", ("numbered", "bold"))
            self._insert(strip_inline_md(nm.group(2)), ("numbered",))
            self._first_line = False
            return True
        bw = _BOLD_WRAP_RE.match(stripped)
        if bw:
            self._insert_newline()
            self._insert(strip_inline_md(stripped), ("bold",))
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
        md_lang = (not lang or lang.lower() in ("markdown", "md", "text"))
        if _depth < 2 and (
            (md_lang and _MD_IN_FENCE_RE.search(content))
            # A markdown table the model fenced (e.g. ```plaintext) — render it
            # as a real table regardless of the fence language.
            or _fence_has_md_table(content)
        ):
            self.render(content, _depth + 1)
        else:
            self._insert_newline()
            w = CodeBlockWidget(
                self._tw, content,
                language=lang, is_dark=self._is_dark,
                width=_logical_px(self._parent, self._initial_code_width()),
            )
            self._tw.window_create("end", window=w, padx=0, pady=4,
                                   stretch=1)
            self._code_blocks.append(w)
            w.bind("<Configure>", self._on_embed_resize, add="+")
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
            width=_logical_px(self._parent, self._initial_code_width()),
        )
        self._tw.window_create("end", window=w, padx=0, pady=4,
                               stretch=1)
        self._code_blocks.append(w)
        w.bind("<Configure>", self._on_embed_resize, add="+")
        self._first_line = False
        return i

    def _parse_table_block(self, lines: list[str], i: int) -> int:
        table_lines: list[str] = []
        while i < len(lines):
            s = lines[i].strip()
            if s.startswith("|"):
                table_lines.append(s)
            elif "-" in s and _ASCII_RULE_RE.match(s):
                # +-----+ border the model drew around the table (top/mid/
                # bottom) — absorb it so it doesn't split the table into
                # fragments and a stray line.
                pass
            else:
                break
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
            w.bind("<Configure>", self._on_embed_resize, add="+")
            self._first_line = False
        return i

    def _on_embed_resize(self, event=None) -> None:
        """Refit when an embedded table/code block changes size.

        Embedded widgets settle asynchronously (TableWidget calls
        ``_deferred_resize`` at 200ms, ``_on_grid_configure`` fires after
        labels measure, etc.). If they finalize *after* the renderer's
        last scheduled ``_resize_to_fit`` (400ms), the bubble's frozen
        ``pack_propagate(False)`` height ends up too short for the
        content and the textbox becomes internally scrollable. Debounce
        a refit so each settle-cycle updates the bubble height too.
        """
        # Ignore the <Configure> echo of our own geometry writes — otherwise
        # _resize_to_fit -> configure() -> <Configure> -> _on_embed_resize ->
        # _resize_to_fit loops forever.
        if self._in_resize or self._suppress_embed_resize:
            return
        # Ignore pure POSITION changes. Scrolling the outer chat moves these
        # embedded widgets, which fires <Configure> with an UNCHANGED width/
        # height. Reacting to those re-runs _resize_to_fit (and its
        # update_idletasks) on every scroll tick, which on Windows shows as
        # text ghosting / re-rendering as you scroll. Only a real size change
        # needs a refit. (Cross-platform-correct; also trims wasted work on
        # macOS, where the repaint was simply not visible.)
        if event is not None and getattr(event, "widget", None) is not None:
            size = (event.width, event.height)
            w = event.widget
            if getattr(w, "_emb_last_size", None) == size:
                return
            try:
                w._emb_last_size = size
            except Exception:
                pass
        if self._resize_timer:
            try:
                self._parent.after_cancel(self._resize_timer)
            except Exception:
                pass
        self._resize_timer = self._parent.after(80, self._resize_to_fit)

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
                self._insert(strip_inline_md(q), ("blockquote",))
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
        """Set the parent frame height to fit content.

        Idempotent: every geometry write below is skipped when the value is
        unchanged, so once the layout settles this method mutates nothing,
        emits no <Configure>, and _on_embed_resize stops rescheduling it.
        That is what breaks the indefinite wider/narrower table oscillation.
        """
        if self._in_resize:
            return
        self._in_resize = True
        # Suppress the <Configure> events the configure() calls below queue,
        # so they don't re-arm this reflow; released after Tk settles them.
        self._suppress_embed_resize = True
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

            # Commit the measured height. With wrap="word" this height depends
            # on the textbox WIDTH, so an early pass (before the textbox reaches
            # its final width) over-wraps and over-measures; that is corrected
            # by _on_textbox_configure, which re-runs this measurement when the
            # width settles to its final value and commits the (shorter) correct
            # height. The `h != _applied_parent_h` guard makes it idempotent
            # once stable, so it converges and never oscillates.
            if h != self._applied_parent_h:
                self._applied_parent_h = h
                self._parent.configure(height=_logical_px(self._parent, h))
                self.text_widget.configure(
                    height=_logical_px(self.text_widget, h))
            # Resize embedded widgets to textbox width
            try:
                tw_width = tw.winfo_width()
                if tw_width > 1:
                    padx = int(str(tw.cget("padx") or 0))
                    embed_w = tw_width - padx * 2
                    # Clamp code-block frames so the right-aligned Copy button
                    # can never overflow off-screen. A wide wrap="none" code
                    # block inflates the textbox, so the raw embed_w can exceed
                    # the bubble's real content area. self._max_width is the
                    # bubble's intended (viewport-derived) content width and is
                    # NOT inflated, so it is the reliable cap; we also cap by
                    # the viewport canvas as a backstop.
                    cap = self._max_width - padx * 2
                    vp_w = self._viewport_width()
                    if vp_w > 1:
                        cap = min(cap, vp_w - padx * 2)
                    cb_embed_w = min(embed_w, cap) if cap > 1 else embed_w
                    for tbl in self._tables:
                        # Clamp the table frame to the bubble width too. If it
                        # keeps the raw (inflated) embed_w, its frame grows as
                        # wide as its own content, so nothing overflows the
                        # canvas -> no horizontal scrollbar, and it spills past
                        # the viewport. Clamping makes the frame narrower than
                        # the natural grid, so the overflow shows a scrollbar.
                        if getattr(tbl, "_rf_embed_w", None) != cb_embed_w:
                            tbl._rf_embed_w = cb_embed_w
                            # CTk frame -> logical; raw-tk canvas inside
                            # _resize_to_width stays physical.
                            tbl.configure(width=_logical_px(tbl, cb_embed_w))
                            tbl._resize_to_width(cb_embed_w)
                        # Force TableWidget height to track its grid's
                        # current reqheight. Read it AFTER an idle update so it
                        # reflects the current (post-relayout) wrap state — a
                        # stale, too-tall reqheight here would inflate the
                        # bubble's ypixels and leave a phantom gap below it.
                        try:
                            tbl._grid.update_idletasks()
                            grid_h = tbl._grid.winfo_reqheight()
                            if grid_h > 1:
                                sb_h = (getattr(tbl, "_SB_H", 12)
                                        if tbl._scrollbar_visible else 0)
                                table_h = grid_h + sb_h
                                if getattr(tbl, "_rf_h", None) != table_h:
                                    tbl._rf_h = table_h
                                    tbl._canvas.configure(height=grid_h)
                                    tbl.configure(
                                        height=_logical_px(tbl, table_h))
                        except Exception:
                            pass
                    for cb in self._code_blocks:
                        if getattr(cb, "_rf_w", None) != cb_embed_w:
                            cb._rf_w = cb_embed_w
                            cb.configure(width=_logical_px(cb, cb_embed_w))
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self._in_resize = False
            # Release suppression only after Tk has drained the <Configure>
            # echoes queued by the configure() calls above. A single after_idle
            # races those echoes (same idle phase, no ordering guarantee); chain
            # a second so suppression outlives them and they cannot re-arm the
            # 80ms refit timer in _on_embed_resize.
            try:
                self._parent.after_idle(
                    self._parent.after_idle,
                    self._end_suppress_embed_resize)
            except Exception:
                self._suppress_embed_resize = False

    def _end_suppress_embed_resize(self) -> None:
        self._suppress_embed_resize = False

    def _initial_code_width(self) -> int:
        """Best initial width for a code block, so it renders full-width at
        creation instead of popping from CTkFrame's ~200px default when the
        first _resize_to_fit fires. Matches the final embed width formula:
        bubble content width (self._max_width) minus the CTkTextbox pack padx
        (16*2) and the inner tk.Text padx (8*2) = 48.
        """
        return max(self._max_width - 48, 120)

    def _viewport_width(self) -> int:
        """Width of the enclosing CTkScrollableFrame's viewport canvas, or 0."""
        parent = self._parent
        while parent is not None:
            if isinstance(parent, customtkinter.CTkScrollableFrame):
                try:
                    return parent._parent_canvas.winfo_width()
                except Exception:
                    return 0
            parent = getattr(parent, "master", None)
        return 0

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
