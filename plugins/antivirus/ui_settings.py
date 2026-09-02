"""Settings view builder for the Antivirus plugin.

Assembles the settings sub-view from existing card builders.
No new UI logic — purely orchestration.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter

from plugins.antivirus.theme import PAD_X, font
from plugins.antivirus.ui_cards import (
    build_scan_exclusions,
    build_siem_card,
    build_sig_updates_settings_card,
    build_whitelist_card,
)
from utils.i18n import get_text


def build_settings_header(plugin, parent, row):
    """Build the settings view header with back button and title."""
    header = customtkinter.CTkFrame(parent, fg_color="transparent")
    header.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(16, 10))
    # 3-column layout so the title actually sits at the geometric center:
    # [back btn | flexible center w/ title | invisible spacer same width as back]
    header.grid_columnconfigure(0, weight=0, minsize=80)
    header.grid_columnconfigure(1, weight=1)
    header.grid_columnconfigure(2, weight=0, minsize=80)

    back_btn = customtkinter.CTkButton(
        header, text=get_text("antivirus.ui_settings.back"), width=80, height=32,
        corner_radius=8, font=font(12),
        fg_color="transparent",
        hover_color=("#E5E7EB", "#2A2A2C"),
        text_color=("#555555", "#AAAAAA"),
        anchor="w",
        command=plugin._show_main_view,
    )
    back_btn.grid(row=0, column=0, sticky="w")

    customtkinter.CTkLabel(
        header, text="Settings",
        font=font(18, bold=True),
    ).grid(row=0, column=1)

    return row + 1


def build_settings_view(plugin, parent):
    """Build all settings view cards into the given scrollable parent."""
    row = 0
    row = build_settings_header(plugin, parent, row)
    row = build_siem_card(plugin, parent, row)
    row = build_scan_exclusions(plugin, parent, row)
    row = build_whitelist_card(plugin, parent, row)
    row = build_sig_updates_settings_card(plugin, parent, row)

    customtkinter.CTkLabel(parent, text="", height=12).grid(
        row=row, column=0,
    )
