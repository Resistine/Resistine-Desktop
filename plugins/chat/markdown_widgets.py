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
        self.insert("1.0", text)
        self.bind("<Key>", self._readonly)
        self._max_width = max_width
        self.bind("<Configure>", self._autoheight, add="+")

    @staticmethod
    def _readonly(event) -> str | None:
        if event.state & _COPY_MOD and event.keysym.lower() in ("c", "a"):
            return None
        return "break"

    def _autoheight(self, _event=None) -> None:
        self.update_idletasks()
        try:
            result = self.count("1.0", "end-1c", "displaylines")
            lines = (result[0] if isinstance(result, (list, tuple))
                     else result) or 1
            self.configure(height=max(1, int(lines)))
        except Exception:
            pass

    def set_width(self, max_width: int) -> None:
        self._max_width = max_width


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

        super().__init__(master, fg_color=colors["code_bg"], corner_radius=10, **kwargs)

        self._code_text = code_text

        # -- Header row (language label + copy button) ----------------------
        header = customtkinter.CTkFrame(self, fg_color=colors["code_header_bg"],
                                        corner_radius=0)
        header.pack(fill="x", padx=14, pady=(10, 0))

        if language:
            lang_label = customtkinter.CTkLabel(
                header,
                text=language.lower(),
                font=customtkinter.CTkFont(family="Inter", size=11,
                                           weight="bold"),
                text_color=colors["fg"],
                anchor="w",
            )
            lang_label.pack(side="left", padx=(4, 0))

        self._copy_btn = customtkinter.CTkButton(
            header,
            text="Copy",
            width=70,
            height=26,
            font=customtkinter.CTkFont(family="Inter", size=11),
            fg_color=RESISTINE_BLUE if not is_dark else "#1565B0",
            hover_color="#1565B0" if not is_dark else RESISTINE_BLUE,
            text_color="#FFFFFF",
            corner_radius=6,
            command=self._copy_to_clipboard,
        )
        self._copy_btn.pack(side="right", padx=(0, 4))

        # -- Code body ------------------------------------------------------
        mono_font = fonts["code"]
        self._code_widget = tk.Text(
            self,
            wrap="none",
            bg=colors["code_bg"],
            fg=colors["code_fg"],
            font=mono_font,
            borderwidth=0,
            padx=14,
            pady=10,
            highlightthickness=0,
            relief="flat",
            insertwidth=0,
        )
        self._code_widget.pack(fill="both", expand=True, padx=0, pady=(6, 10))
        self._code_widget.insert("1.0", code_text)

        # Auto-height: cap at 25 visible lines to avoid giant blocks
        line_count = code_text.count("\n") + 1
        visible = min(25, max(3, line_count + 1))
        self._code_widget.configure(state="disabled", height=visible)

    # -- Clipboard ----------------------------------------------------------

    def _copy_to_clipboard(self) -> None:
        """Copy the code text and flash confirmation on the button."""
        try:
            self.clipboard_clear()
            self.clipboard_append(self._code_text)
            self._copy_btn.configure(text="Copied!")
            self.after(1500, lambda: self._copy_btn.configure(text="Copy"))
        except Exception as exc:
            logger.warning(f"Clipboard copy failed: {exc}")
            self._copy_btn.configure(text="Failed")
            self.after(1500, lambda: self._copy_btn.configure(text="Copy"))


# ---------------------------------------------------------------------------
# TableWidget
# ---------------------------------------------------------------------------

class TableWidget(customtkinter.CTkFrame):
    """GitHub-style markdown table rendered as a grid of labels.

    Constructor
    -----------
    master : widget
        Parent container.
    headers : list[str]
        Column header strings.
    rows : list[list[str]]
        Data rows; each inner list has one string per column.
    is_dark : bool
        True for dark-mode palette, False for light.
    """

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

        super().__init__(master, fg_color=border_clr, corner_radius=0, **kwargs)

        self._num_cols = max(len(headers), *(len(r) for r in rows)) if rows else len(headers)
        self._labels: list[tk.Label] = []

        # Inner frame that holds the actual grid (sits inside the border)
        self._grid = tk.Frame(self, bg=border_clr, highlightthickness=1,
                              highlightbackground=border_clr, bd=0)
        self._grid.pack(fill="both", expand=True)

        for j in range(self._num_cols):
            self._grid.grid_columnconfigure(j, weight=1)

        all_rows: list[tuple[list[str], bool]] = [(headers, True)]
        for r in rows:
            all_rows.append((r, False))

        header_font = customtkinter.CTkFont(family="Inter", size=13,
                                            weight="bold")
        body_font = customtkinter.CTkFont(family="Inter", size=13)

        for idx, (row_cells, is_header) in enumerate(all_rows):
            # Pad short rows
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
                    self._grid,
                    text=cell_text,
                    bg=bg,
                    fg=(colors["heading"] if is_header else colors["fg"]),
                    font=header_font if is_header else body_font,
                    padx=10,
                    pady=6,
                    anchor="w",
                    justify="left",
                )
                lbl.grid(
                    row=idx, column=j, sticky="nsew",
                    padx=(1 if j > 0 else 0, 0),
                    pady=(1 if idx > 0 else 0, 0),
                )
                self._labels.append(lbl)

        # Reflow column widths when the parent resizes
        self.bind("<Configure>", self._on_configure)

    # -- Reflow -------------------------------------------------------------

    def _on_configure(self, event) -> None:
        """Recalculate wraplength for labels when the widget width changes."""
        width = event.width
        if width <= 1 or self._num_cols == 0:
            return

        usable = width - 40
        col_width = max(int(usable / self._num_cols) - 24, 50)

        for lbl in self._labels:
            try:
                lbl.configure(wraplength=col_width)
            except tk.TclError:
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
