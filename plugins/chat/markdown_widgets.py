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

from plugins.chat.fonts import RESISTINE_BLUE, get_fonts, get_theme_colors
from utils.logger import logger

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
        """Set widget width to fit text content, up to max_width."""
        try:
            import tkinter.font as tkfont
            if hasattr(font, "actual"):
                measure_font = font
            else:
                measure_font = tkfont.Font(font=font)
            text_px = measure_font.measure(text)
            width_px = min(text_px + 4, max_width)
            avg_char = measure_font.measure("0") or 8
            char_width = max(1, -(-width_px // avg_char))
            self.configure(width=char_width)
        except Exception:
            pass

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
            result = self.count("1.0", "end-1c", "displaylines")
            lines = (result[0] if isinstance(result, (list, tuple))
                     else result) or 1
            new_h = max(1, int(lines))
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
            result = self.count("1.0", "end-1c", "displaylines")
            lines = (result[0] if isinstance(result, (list, tuple))
                     else result) or 1
            if int(lines) <= 1:
                self.tag_add("center", "1.0", "end")
            else:
                self.tag_remove("center", "1.0", "end")
        except Exception:
            pass

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
                    family="Inter", size=10),
                text_color=muted_fg, anchor="w",
            )
            lang_label.pack(side="left", padx=(14, 0), pady=6)

        self._copy_btn = customtkinter.CTkButton(
            header, text="Copy", width=56, height=24,
            font=customtkinter.CTkFont(family="Inter", size=10),
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
        self._canvas.pack(fill="both", expand=True)
        # Scrollbar hidden initially; shown only when needed
        self._scrollbar_visible = False

        all_rows: list[tuple[list[str], bool]] = [(headers, True)]
        for r in rows:
            all_rows.append((r, False))

        header_font = customtkinter.CTkFont(family="Inter", size=13,
                                            weight="bold")
        body_font = customtkinter.CTkFont(family="Inter", size=13)

        # Measure content to set minimum column widths
        import tkinter.font as tkfont
        measure = tkfont.Font(family="Inter", size=13)
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
                lbl = tk.Label(
                    self._grid, text=cell_text, bg=bg,
                    fg=(colors["heading"] if is_header
                        else colors["fg"]),
                    font=header_font if is_header else body_font,
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
        self._grid.bind("<Configure>", self._on_grid_configure)
        self.bind("<Configure>", self._on_configure)
        self.after(200, self._deferred_resize)

    def _on_grid_configure(self, _event=None) -> None:
        """Update canvas scroll region and height when grid changes."""
        try:
            bbox = self._canvas.bbox("all")
            if bbox:
                self._canvas.configure(
                    scrollregion=bbox,
                    height=bbox[3] - bbox[1],
                )
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
        """Resize table internals to the given width."""
        if self._in_resize:
            return
        self._in_resize = True
        self._last_width = width
        try:
            natural_width = self._natural_width
            if natural_width <= width:
                self._canvas.configure(width=width)
                self._canvas.itemconfigure(
                    self._canvas_window, width=width)
                col_width = max(int(width / self._num_cols) - 12, 50)
                for lbl in self._labels:
                    try:
                        lbl.configure(wraplength=col_width)
                    except tk.TclError:
                        pass
            else:
                self._canvas.itemconfigure(
                    self._canvas_window, width=natural_width)
                for lbl in self._labels:
                    try:
                        lbl.configure(wraplength=0)
                    except tk.TclError:
                        pass
            self._on_grid_configure()
            self._update_scrollbar()
        finally:
            self._in_resize = False

    def _update_scrollbar(self) -> None:
        """Show scrollbar only when content overflows horizontally."""
        try:
            self._canvas.update_idletasks()
            bbox = self._canvas.bbox("all")
            if not bbox:
                return
            content_w = bbox[2] - bbox[0]
            visible_w = self._canvas.winfo_width()
            if content_w > visible_w and not self._scrollbar_visible:
                self._scrollbar.pack(fill="x")
                self._scrollbar_visible = True
            elif content_w <= visible_w and self._scrollbar_visible:
                self._scrollbar.pack_forget()
                self._scrollbar_visible = False
        except Exception:
            pass


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
