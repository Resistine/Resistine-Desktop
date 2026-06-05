##@file plugins/chat/markdown_widgets.py
"""
Markdown Widgets — Standalone CTkFrame widgets for code blocks, tables,
and horizontal rules inside chat bubbles.

These replace the old window_create embedded widgets from MarkdownBubble,
providing self-contained components that can be pack()'d into any parent.

Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import sys
import tkinter as tk

import customtkinter

from plugins.chat.fonts import (
    RESISTINE_BLUE, get_fonts, get_theme_colors, ui_family, ui_size,
)
from plugins.chat.markdown_bubble import (
    _EMOJI_RE, _EMOJI_RENDER, MarkdownBubble, attach_emoji_copy,
)
from utils.logger import logger


def _cell_has_emoji(text: str) -> bool:
    """Linux-only check: cell text needs the image-emoji path."""
    return bool(
        _EMOJI_RENDER and _EMOJI_RE is not None and _EMOJI_RE.search(text))


def _make_emoji_cell_text(
    parent: tk.Widget, text: str, bg: str, fg: str, font,
) -> tk.Text:
    """A label-like tk.Text widget that renders inline colour emoji.

    Used in table cells on Linux when the cell text contains emoji
    codepoints — tk.Label can't fall back per-glyph to a colour-emoji
    font, but tk.Text supports inline images.
    """
    tw = tk.Text(
        parent, wrap="word", font=font, fg=fg, bg=bg,
        borderwidth=0, highlightthickness=0, relief="flat",
        insertwidth=0, cursor="", padx=10, pady=6,
        height=1, width=1,
    )
    photos: list[object] = []
    image_to_emoji: dict[str, str] = {}
    for i, part in enumerate(_EMOJI_RE.split(text)):
        if not part:
            continue
        if i % 2 == 1:
            for ch in MarkdownBubble._split_emoji_chars(part):
                photo = MarkdownBubble._render_emoji(ch)
                if photo:
                    photos.append(photo)
                    img_name = tw.image_create(
                        "end", image=photo, padx=1)
                    image_to_emoji[img_name] = ch
                else:
                    tw.insert("end", ch)
        else:
            tw.insert("end", part)
    tw._emoji_photos = photos  # type: ignore[attr-defined]
    tw._image_to_emoji = image_to_emoji  # type: ignore[attr-defined]
    attach_emoji_copy(tw, image_to_emoji)
    tw.configure(state="disabled")

    # Auto-size height to displayed lines as the column resizes.
    state = {"busy": False}

    def _autoheight(_event=None, w=tw, s=state):
        if s["busy"]:
            return
        s["busy"] = True
        try:
            # Measure in pixels. tk.Text's ``-height`` is in font-line
            # units, but an inline emoji image is typically taller than
            # the font's linespace, so a "one display line" cell ends up
            # shorter than the image and clips it. Compute the line count
            # that covers the actual rendered pixel height instead.
            import tkinter.font as tkfont
            font_obj = tkfont.Font(font=w.cget("font"))
            font_lh = max(1, font_obj.metrics("linespace"))
            yp = w.count("1.0", "end", "ypixels")
            if yp is None:
                new_h = 1
            else:
                content_px = yp[0] if isinstance(yp, (list, tuple)) else yp
                new_h = max(1, -(-int(content_px) // font_lh))
            if int(w.cget("height")) != new_h:
                w.configure(height=new_h)
        except Exception:
            pass
        finally:
            s["busy"] = False

    tw.bind("<Configure>", _autoheight, add="+")
    return tw

_COPY_MOD = 0x8 if sys.platform == "darwin" else 0x4  # Cmd on mac, Ctrl elsewhere


# ---------------------------------------------------------------------------
# SelectableLabel
# ---------------------------------------------------------------------------

class SelectableLabel(tk.Text):
    """Read-only text widget that looks like a label but allows selection + copy."""

    def __init__(
        self, master, text: str, font, fg: str, bg: str,
        max_width: int = 600, **kwargs,
    ):
        kwargs.pop("padx", None)
        kwargs.pop("pady", None)
        super().__init__(
            master, wrap="word", font=font, fg=fg, bg=bg,
            borderwidth=0, highlightthickness=0, relief="flat",
            insertwidth=0, cursor="", selectbackground="#3A6DB5",
            selectforeground="#FFFFFF", height=1, **kwargs,
        )
        self.tag_configure("center", justify="center")
        self.insert("1.0", text)
        self.bind("<Key>", self._readonly)
        self._max_width = max_width
        self._in_autoheight = False
        self._fit_width(font, text, max_width)
        self._update_justify()
        self.bind("<Configure>", self._autoheight, add="+")

    def _fit_width(self, font, text: str, max_width: int) -> None:
        """Size the widget to HUG the text, up to max_width.

        A message that fits on one line gets a bubble exactly that wide. A
        message that wraps is sized to its LONGEST WRAPPED LINE rather than the
        full max_width — otherwise a right-aligned user bubble shows a wide
        empty band to the right of the shorter wrapped lines.
        """
        try:
            import tkinter.font as tkfont
            if hasattr(font, "actual"):
                measure_font = font
            else:
                measure_font = tkfont.Font(font=font)
            one_line_px = measure_font.measure(text.replace("\n", " "))
            if one_line_px + 4 <= max_width:
                width_px = one_line_px + 4
            else:
                longest = self._wrapped_max_line_px(
                    measure_font, text, max_width)
                width_px = min(longest + 4, max_width)
            avg_char = measure_font.measure("0") or 8
            char_width = max(1, -(-width_px // avg_char))
            self.configure(width=char_width)
        except Exception:
            pass

    @staticmethod
    def _wrapped_max_line_px(measure_font, text: str, max_width: int) -> int:
        """Greedy word-wrap *text* at *max_width* px (matching wrap="word");
        return the pixel width of the widest resulting line."""
        widest = 0
        for paragraph in text.split("\n"):
            cur = ""
            for word in paragraph.split(" "):
                trial = word if not cur else cur + " " + word
                if not cur or measure_font.measure(trial) <= max_width:
                    cur = trial
                else:
                    widest = max(widest, measure_font.measure(cur))
                    cur = word
            widest = max(widest, measure_font.measure(cur))
        return widest

    @staticmethod
    def _readonly(event) -> str | None:
        if event.state & _COPY_MOD and event.keysym.lower() in ("c", "a"):
            return None
        return "break"

    def _autoheight(self, _event=None) -> None:
        if self._in_autoheight:
            return
        self._in_autoheight = True
        try:
            lines = self._displayline_count()
            new_h = max(1, lines)
            cur_h = int(self.cget("height"))
            if new_h != cur_h:
                self.configure(height=new_h)
            self._update_justify()
        except Exception:
            pass
        finally:
            self._in_autoheight = False

    def _update_justify(self) -> None:
        """Center text when it fits on one line, left-align otherwise."""
        try:
            if self._displayline_count() <= 1:
                self.tag_add("center", "1.0", "end")
            else:
                self.tag_remove("center", "1.0", "end")
        except Exception:
            pass

    def _displayline_count(self) -> int:
        """Number of rendered display lines from 1.0 to end-1c.

        Tk's ``count -displaylines`` returns the number of line
        *boundaries* crossed (newlines + wrap points), not the number of
        lines themselves -- so a 2-line message returns ``(1,)`` and a
        1-line message returns ``None``. Add 1 to get the actual count.
        """
        result = self.count("1.0", "end-1c", "displaylines")
        if result is None:
            return 1
        breaks = result[0] if isinstance(result, (list, tuple)) else result
        return int(breaks) + 1

    def set_width(self, max_width: int) -> None:
        if max_width == self._max_width:
            return
        self._max_width = max_width
        # Re-fit the widget so it actually grows/shrinks when the parent
        # chat area resizes (e.g. when chat_scroll lays out to full size
        # after the bubble has already been created).
        text = self.get("1.0", "end-1c")
        self._fit_width(self.cget("font"), text, max_width)


# ---------------------------------------------------------------------------
# CodeBlockWidget
# ---------------------------------------------------------------------------

class CodeBlockWidget(customtkinter.CTkFrame):
    """Fenced code block with language label, copy button, and monospace body.

    Constructor
    -----------
    master : widget
        Parent container (any tkinter or CTk widget).
    code_text : str
        The raw source code to display.
    language : str
        Optional language identifier shown in the header.
    is_dark : bool
        True for dark-mode palette, False for light.
    """

    def __init__(
        self,
        master,
        code_text: str,
        language: str = "",
        is_dark: bool = False,
        **kwargs,
    ):
        colors = get_theme_colors(is_dark)
        fonts = get_fonts(is_dark)

        muted_fg = "#888888"
        sb_color = "#3A3A3C" if is_dark else "#C8C8CC"
        sb_hover = "#555558" if is_dark else "#A8A8AC"

        super().__init__(
            master, fg_color=colors["code_bg"], corner_radius=12,
            **kwargs)

        self._code_text = code_text

        # -- Header row (flush with body, children have padding) ------------
        header = customtkinter.CTkFrame(
            self, fg_color=colors["code_header_bg"], corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)

        if language:
            lang_label = customtkinter.CTkLabel(
                header, text=language.lower(),
                font=customtkinter.CTkFont(
                    family=ui_family(), size=ui_size(10, win_bump=2)),
                text_color=muted_fg, anchor="w",
            )
            lang_label.pack(side="left", padx=(14, 0), pady=6)

        self._copy_btn = customtkinter.CTkButton(
            header, text="Copy", width=56, height=24,
            font=customtkinter.CTkFont(family=ui_family(), size=ui_size(10, win_bump=2)),
            fg_color=RESISTINE_BLUE, hover_color="#1565B0",
            text_color="#FFFFFF",
            corner_radius=6, command=self._copy_to_clipboard,
        )
        self._copy_btn.pack(side="right", padx=(0, 10), pady=5)

        # -- Code body ------------------------------------------------------
        mono_font = fonts["code"]
        self.pack_propagate(False)

        self._code_widget = tk.Text(
            self, wrap="none", width=1,
            bg=colors["code_bg"], fg=colors["code_fg"],
            font=mono_font, borderwidth=0,
            padx=14, pady=10, highlightthickness=0,
            relief="flat", insertwidth=0,
        )
        self._code_widget.insert("1.0", code_text)

        line_count = code_text.count("\n") + 1
        visible = min(line_count, 25)
        self._code_widget.configure(state="disabled", height=visible)
        self._code_widget.pack(
            fill="both", expand=True, padx=0, pady=(0, 0))

        # Set frame height: header(32) + text lines + padding + scrollbar
        import tkinter.font as tkfont
        try:
            line_h = tkfont.Font(font=mono_font).metrics("linespace")
        except Exception:
            line_h = 20
        # header(32) + text(lines*lineheight + pady*2) + scrollbar(14) + buffer
        frame_h = 32 + visible * line_h + 20 + 14 + 10
        # frame_h is a PHYSICAL measurement (line_h from raw tkfont metrics);
        # CTk's configure(height=) multiplies by display scaling, so divide it
        # out or the code block is scaling-factor times too tall on a Windows
        # 125% display (which also inflates the bubble height).
        try:
            _s = customtkinter.ScalingTracker.get_widget_scaling(self)
            if _s:
                frame_h = int(round(frame_h / _s))
        except Exception:
            pass
        self.configure(height=frame_h)

        # -- Horizontal scrollbar (always visible) --------------------------
        scrollbar = customtkinter.CTkScrollbar(
            self, orientation="horizontal",
            command=self._code_widget.xview,
            height=10, corner_radius=5,
            fg_color=colors["code_bg"],
            button_color=sb_color,
            button_hover_color=sb_hover)
        self._code_widget.configure(
            xscrollcommand=scrollbar.set)
        scrollbar.pack(fill="x", padx=8, pady=(0, 4))

    # -- Clipboard ----------------------------------------------------------

    def _copy_to_clipboard(self) -> None:
        """Copy the code text and flash confirmation on the button."""
        try:
            self.clipboard_clear()
            self.clipboard_append(self._code_text)
            self._copy_btn.configure(text="Copied!")
            self.after(1200, lambda: self._copy_btn.configure(text="Copy"))
        except Exception as exc:
            logger.warning(f"Clipboard copy failed: {exc}")
            self._copy_btn.configure(text="Failed")
            self.after(1200, lambda: self._copy_btn.configure(text="Copy"))


# ---------------------------------------------------------------------------
# TableWidget
# ---------------------------------------------------------------------------

class TableWidget(customtkinter.CTkFrame):
    """GitHub-style markdown table with horizontal scroll for wide tables."""

    def __init__(
        self,
        master,
        headers: list[str],
        rows: list[list[str]],
        is_dark: bool = False,
        **kwargs,
    ):
        colors = get_theme_colors(is_dark)
        border_clr = colors.get("table_header_bg", "#D4D4D8")
        canvas_bg = colors.get("table_alt_bg", border_clr)

        super().__init__(master, fg_color=border_clr, corner_radius=0,
                         **kwargs)

        # Hold the size we are told to be. Without this the frame propagates
        # to its canvas content, which fights the explicit width/height the
        # markdown renderer force-applies every reflow pass — the two
        # authorities disagree at some window widths and the table oscillates
        # wider/narrower forever. pack_propagate(False) makes our configured
        # size authoritative so the reflow converges to a fixed point.
        self.pack_propagate(False)

        self._num_cols = (max(len(headers), *(len(r) for r in rows))
                          if rows else len(headers))
        self._labels: list[tk.Label] = []

        # Scrollable canvas wrapper
        self._canvas = tk.Canvas(
            self, bg=canvas_bg, highlightthickness=0, bd=0)
        sb_color = "#3A3A3C" if is_dark else "#C8C8CC"
        sb_hover = "#555558" if is_dark else "#A8A8AC"
        self._scrollbar = customtkinter.CTkScrollbar(
            self, orientation="horizontal",
            command=self._canvas.xview,
            height=10, corner_radius=5,
            fg_color=border_clr,
            button_color=sb_color,
            button_hover_color=sb_hover)
        self._canvas.configure(xscrollcommand=self._scrollbar.set)
        # Always reserve a scrollbar row at the bottom (like code blocks).
        # Packing it conditionally fought the renderer's frame-height sizing and
        # left the freshly-packed bar clipped to zero height -> invisible. With
        # it always on, the thumb is full-width when the table fits and scrolls
        # when it overflows; sb height is constant so nothing oscillates.
        self._scrollbar.pack(side="bottom", fill="x")
        self._canvas.pack(side="top", fill="both", expand=True)
        self._scrollbar_visible = True

        all_rows: list[tuple[list[str], bool]] = [(headers, True)]
        for r in rows:
            all_rows.append((r, False))

        # Use the shared chat body/bold fonts so table text matches the size
        # and family of everything else in the conversation.
        _tbl_fonts = get_fonts(is_dark)
        header_font = _tbl_fonts["bold"]
        body_font = _tbl_fonts["body"]

        # Measure with the actual body font so column widths match the text.
        measure = body_font
        self._col_min_px = [0] * self._num_cols
        for row_cells, _ in all_rows:
            for j in range(self._num_cols):
                txt = row_cells[j] if j < len(row_cells) else ""
                self._col_min_px[j] = max(
                    self._col_min_px[j], measure.measure(txt) + 24)
        self._col_min_px = [max(px, 60) for px in self._col_min_px]

        # Grid frame inside the canvas — set explicit min width
        self._natural_width = sum(self._col_min_px) + self._num_cols
        self._grid = tk.Frame(self._canvas, bg=border_clr,
                              highlightthickness=0, bd=0,
                              width=self._natural_width)
        self._grid.grid_propagate(True)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._grid, anchor="nw",
            width=self._natural_width)

        for j in range(self._num_cols):
            self._grid.grid_columnconfigure(
                j, weight=1, minsize=self._col_min_px[j])

        for idx, (row_cells, is_header) in enumerate(all_rows):
            while len(row_cells) < self._num_cols:
                row_cells.append("")

            if is_header:
                bg = colors["table_header_bg"]
            elif idx % 2 == 0:
                bg = colors["table_alt_bg"]
            else:
                bg = colors["bubble_bg"]
                if bg == "transparent":
                    try:
                        bg = master.cget("bg")
                    except Exception:
                        bg = master.winfo_toplevel().cget("bg")

            for j, cell_text in enumerate(row_cells):
                cell_fg = colors["heading"] if is_header else colors["fg"]
                cell_font = header_font if is_header else body_font
                if _cell_has_emoji(cell_text):
                    lbl = _make_emoji_cell_text(
                        self._grid, cell_text, bg, cell_fg, cell_font,
                    )
                else:
                    lbl = tk.Label(
                        self._grid, text=cell_text, bg=bg,
                        fg=cell_fg, font=cell_font,
                        padx=10, pady=6, anchor="w", justify="left",
                        wraplength=0,
                    )
                lbl.grid(
                    row=idx, column=j, sticky="nsew",
                    padx=(1 if j > 0 else 0, 0),
                    pady=(1 if idx > 0 else 0, 0),
                )
                self._labels.append(lbl)

        self._in_resize = False
        self._last_width = 0
        self._last_grid_bbox: tuple[int, int, int, int] | None = None
        self._grid.bind("<Configure>", self._on_grid_configure)
        self.bind("<Configure>", self._on_configure)
        self.after(200, self._deferred_resize)

    def _on_grid_configure(self, _event=None) -> None:
        """Update canvas scroll region and height when grid changes.

        Guarded against no-op invocations: scrolling the outer chat can
        fire <Configure> on the embedded grid even when its bbox hasn't
        moved, and re-asserting ``configure(height=...)`` on the inner
        canvas cascades back up the parent chain (bubble reflow ->
        chat_scroll <Configure>) producing a single-frame jitter per
        scroll tick.

        Use ``self._grid.winfo_reqheight()`` for height rather than
        ``self._canvas.bbox("all")``: when cells autoheight, the grid's
        reqheight grows immediately, but the canvas's bbox can return a
        stale value cached from the embedded window-item's earlier size.
        That stale bbox left TableWidget pinned at CTkFrame's default
        200 px, even when its real content was taller, and the embed's
        actual rendered content overflowed past its window_create line.
        """
        try:
            bbox = self._canvas.bbox("all")
            grid_h = self._grid.winfo_reqheight()
            if not bbox:
                if grid_h <= 1:
                    return
                width = self._natural_width
                content_h = grid_h
            else:
                width = bbox[2] - bbox[0]
                content_h = max(grid_h, bbox[3] - bbox[1])
            new_state = (width, content_h)
            if new_state == self._last_grid_bbox:
                return
            self._last_grid_bbox = new_state
            self._canvas.configure(
                scrollregion=(0, 0, width, content_h),
                height=content_h,
            )
            # Re-evaluate the horizontal scrollbar here too. _update_scrollbar
            # otherwise runs only inside _resize_to_width, which early-returns
            # on an unchanged width — so the very first evaluation can happen
            # before the grid has laid out (bbox is None) and then never re-run.
            # The grid's <Configure> fires once it has real content, which is
            # exactly when the overflow decision becomes valid.
            self._update_scrollbar()
        except Exception:
            pass

    def _deferred_resize(self) -> None:
        """Re-layout after stretch has taken effect."""
        try:
            w = self.winfo_width()
            if w > 1:
                self._resize_to_width(w)
        except Exception:
            pass

    def _on_configure(self, event) -> None:
        width = event.width
        if width > 1 and self._num_cols > 0 and width != self._last_width:
            self._resize_to_width(width)

    def _resize_to_width(self, width: int) -> None:
        """Resize table internals to the given width.

        Idempotent on width: re-applying the same width re-wraps cells and
        re-asserts canvas geometry for no reason, which can re-fire the
        <Configure> cascade. Skip when the width has not actually changed.
        """
        if self._in_resize or width == self._last_width:
            return
        self._in_resize = True
        self._last_width = width
        try:
            natural_width = self._natural_width
            # Never wrap cell text: data/terminal tables should keep each row
            # on one line and scroll HORIZONTALLY when wider than the bubble.
            for lbl in self._labels:
                try:
                    lbl.configure(wraplength=0)
                except tk.TclError:
                    pass
            if natural_width <= width:
                # Fits — stretch the grid to fill the bubble (columns share the
                # extra space via their grid weights); no scrollbar needed.
                self._canvas.configure(width=width)
                self._canvas.itemconfigure(
                    self._canvas_window, width=width)
            else:
                # Wider than the bubble — render at full content width and let
                # the horizontal scrollbar handle the overflow.
                self._canvas.itemconfigure(
                    self._canvas_window, width=natural_width)
            self._on_grid_configure()
            self._update_scrollbar()
        finally:
            self._in_resize = False

    # Hysteresis dead-band for the horizontal-scrollbar show/hide decision.
    # Showing the scrollbar adds ~14px of frame height (sb_h in
    # markdown_renderer._resize_to_fit); without a dead-band that height delta
    # reflows the bubble, shifts the canvas width 1-2px, and re-crosses a single
    # bare threshold every reflow pass -> the table oscillates wider/narrower
    # forever at certain window widths/DPIs. _SB_HIDE_MARGIN must exceed sb_h
    # (14) so the scrollbar's own height cannot re-cross the hide threshold,
    # making _scrollbar_visible a per-width monotone latch that pins sb_h and
    # lets the reflow reach a fixed point.
    _SB_SHOW_MARGIN = 2
    _SB_HIDE_MARGIN = 16

    _SB_H = 12  # horizontal scrollbar height + a little breathing room

    def _update_scrollbar(self) -> None:
        """No-op: the horizontal scrollbar is always packed (see __init__), so
        there is nothing to show/hide. The canvas xscrollcommand keeps the
        thumb in sync with the content automatically."""
        return


# ---------------------------------------------------------------------------
# HorizontalRule
# ---------------------------------------------------------------------------

class HorizontalRule(customtkinter.CTkFrame):
    """Thin colored strip acting as a markdown horizontal rule (``---``).

    Constructor
    -----------
    master : widget
        Parent container.
    is_dark : bool
        True for dark-mode palette, False for light.
    """

    def __init__(
        self,
        master,
        is_dark: bool = False,
        **kwargs,
    ):
        colors = get_theme_colors(is_dark)
        hr_color = colors["hr"]

        super().__init__(master, fg_color="transparent", corner_radius=0,
                         height=14, **kwargs)

        # Thin visible line
        line = customtkinter.CTkFrame(
            self,
            fg_color=hr_color,
            height=2,
            corner_radius=0,
        )
        line.pack(fill="x", padx=8, pady=(6, 6))

        # Prevent the outer frame from collapsing
        self.pack_propagate(False)
