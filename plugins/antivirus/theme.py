"""Layout helpers for the Antivirus plugin.

This module deliberately defines no colors — widgets here either rely on
their CustomTkinter defaults (which come from the app-wide theme JSON at
resources/themes/resistine_ctk.json) or read named tokens from
ThemeManager at call time. That way the antivirus page tracks any
app-wide palette change without a parallel set of constants.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter
from customtkinter import ThemeManager

CORNER_R = 12
PAD_X = 20
_FONT_FAMILY = "Inter"


def font(size, bold=False):
    weight = "bold" if bold else "normal"
    return customtkinter.CTkFont(family=_FONT_FAMILY, size=size, weight=weight)


def make_card(parent, row):
    card = customtkinter.CTkFrame(
        parent, corner_radius=CORNER_R, border_width=1,
    )
    card.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(0, 6))
    card.grid_columnconfigure(0, weight=1)
    return card


def add_separator(card, row):
    divider = ThemeManager.theme.get("Theme", {}).get("divider_color")
    customtkinter.CTkFrame(
        card, height=1, fg_color=divider,
    ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=16)
    return row + 1


def section_title(parent, text):
    accent = ThemeManager.theme.get("Theme", {}).get("sidebar_active_text")
    return customtkinter.CTkLabel(
        parent, text=text.upper(),
        font=customtkinter.CTkFont(
            family=_FONT_FAMILY, size=12, weight="bold",
        ),
        text_color=accent,
    )
