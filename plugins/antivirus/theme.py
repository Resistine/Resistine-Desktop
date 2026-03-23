"""Shared theme constants and widget helpers for the Antivirus plugin.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter

# UI color tuples: (light, dark)
COLOR_MUTED = ("#6B7280", "#9CA3AF")
COLOR_OK_BG = ("#DCFCE7", "#0A2F1A")
COLOR_OK_TEXT = ("#15803D", "#4ADE80")
COLOR_WARN_BG = ("#FEF3C7", "#2D1F05")
COLOR_WARN_TEXT = ("#92400E", "#FBBF24")
COLOR_CARD_BG = ("#ffffff", "#1A1A1C")
COLOR_CARD_BORDER = ("#E5E7EB", "#2A2A2C")
COLOR_DIVIDER = ("#E5E7EB", "#2A2A2A")
COLOR_BTN_OUTLINE = ("#0D5394", "#2B7DE0")
COLOR_BTN_OUTLINE_HOVER = ("#0B4578", "#1565B0")

CORNER_R = 12
PAD_X = 20
_FONT_FAMILY = "Inter"


def font(size, bold=False):
    weight = "bold" if bold else "normal"
    return customtkinter.CTkFont(family=_FONT_FAMILY, size=size, weight=weight)


def make_card(parent, row):
    card = customtkinter.CTkFrame(
        parent, corner_radius=CORNER_R, fg_color=COLOR_CARD_BG,
        border_width=1, border_color=COLOR_CARD_BORDER,
    )
    card.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(0, 6))
    card.grid_columnconfigure(0, weight=1)
    return card


def add_separator(card, row):
    customtkinter.CTkFrame(
        card, height=1, fg_color=COLOR_DIVIDER,
    ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=16)
    return row + 1
