"""Secondary UI card builders for the Antivirus plugin.

Builds the Whitelist/Quarantine and Signature Updates sections.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter

from plugins.antivirus.theme import (
    COLOR_BTN_OUTLINE,
    COLOR_BTN_OUTLINE_HOVER,
    COLOR_CARD_BG,
    COLOR_CARD_BORDER,
    COLOR_MUTED,
    CORNER_R,
    PAD_X,
    add_separator,
    font,
    make_card,
)


# ── 4. Whitelist + Quarantine ────────────────────────────


def _build_whitelist_card(plugin, container):
    card = customtkinter.CTkFrame(
        container, corner_radius=CORNER_R, fg_color=COLOR_CARD_BG,
        border_width=1, border_color=COLOR_CARD_BORDER,
    )
    card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
    card.grid_columnconfigure(0, weight=1)

    hdr = customtkinter.CTkFrame(card, fg_color="transparent")
    hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
    hdr.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        hdr, text="Whitelist", font=font(14, bold=True),
    ).grid(row=0, column=0, sticky="w")

    customtkinter.CTkButton(
        hdr, text="+ Add", width=60, height=26, corner_radius=6,
        font=font(11), fg_color="transparent", border_width=1,
        border_color=COLOR_BTN_OUTLINE, text_color=COLOR_BTN_OUTLINE,
        hover_color=COLOR_BTN_OUTLINE_HOVER,
        command=lambda: plugin._on_action("whitelist_add"),
    ).grid(row=0, column=1, sticky="e")

    plugin._whitelist_frame = customtkinter.CTkFrame(
        card, fg_color="transparent",
    )
    plugin._whitelist_frame.grid(
        row=1, column=0, padx=16, pady=(0, 14), sticky="ew",
    )
    plugin._whitelist_frame.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        plugin._whitelist_frame, text="No whitelisted paths",
        font=font(12), text_color=COLOR_MUTED,
    ).grid(row=0, column=0, sticky="w")


def _build_quarantine_card(plugin, container):
    card = customtkinter.CTkFrame(
        container, corner_radius=CORNER_R, fg_color=COLOR_CARD_BG,
        border_width=1, border_color=COLOR_CARD_BORDER,
    )
    card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
    card.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        card, text="Quarantine", font=font(14, bold=True),
    ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="w")

    plugin._quarantine_frame = customtkinter.CTkFrame(
        card, fg_color="transparent",
    )
    plugin._quarantine_frame.grid(
        row=1, column=0, padx=16, pady=(0, 14), sticky="ew",
    )
    plugin._quarantine_frame.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        plugin._quarantine_frame, text="No threats quarantined",
        font=font(12), text_color=COLOR_MUTED,
    ).grid(row=0, column=0, sticky="w")


def build_whitelist_and_quarantine(plugin, parent, row):
    container = customtkinter.CTkFrame(
        parent, fg_color="transparent", corner_radius=0,
    )
    container.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(0, 6))
    container.grid_columnconfigure(0, weight=1)
    container.grid_columnconfigure(1, weight=1)

    _build_whitelist_card(plugin, container)
    _build_quarantine_card(plugin, container)
    return row + 1


# ── 5. Signature Updates ────────────────────────────────


def _build_db_info_rows(plugin, card, start_row):
    db_rows = [
        ("Engine", "ClamAV"),
        ("Signatures", "\u2014"),
        ("Last Updated", "\u2014"),
    ]
    plugin._db_labels = {}
    r = start_row
    for label, value in db_rows:
        customtkinter.CTkLabel(
            card, text=label, text_color=COLOR_MUTED, font=font(12),
        ).grid(row=r, column=0, padx=16, pady=(4, 0), sticky="w")
        val_lbl = customtkinter.CTkLabel(
            card, text=value, font=font(12, bold=True),
        )
        val_lbl.grid(row=r, column=1, padx=16, pady=(4, 0), sticky="e")
        plugin._db_labels[label] = val_lbl
        r += 1
    return r


def _build_auto_update_toggle(plugin, card, row):
    auto_row = customtkinter.CTkFrame(card, fg_color="transparent")
    auto_row.grid(
        row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 0),
    )
    auto_row.grid_columnconfigure(0, weight=1)

    left = customtkinter.CTkFrame(auto_row, fg_color="transparent")
    left.grid(row=0, column=0, sticky="w")

    customtkinter.CTkLabel(
        left, text="Auto-update signatures", font=font(12),
    ).grid(row=0, column=0, sticky="w")
    customtkinter.CTkLabel(
        left, text="Daily around 4:00 AM (\u00b12 hrs)",
        font=font(11), text_color=COLOR_MUTED,
    ).grid(row=1, column=0, sticky="w")

    plugin._auto_update_switch = customtkinter.CTkSwitch(
        auto_row, text="", width=44,
        command=plugin._toggle_auto_update,
        onvalue=True, offvalue=False,
    )
    if plugin._auto_update_on:
        plugin._auto_update_switch.select()
    plugin._auto_update_switch.grid(row=0, column=1, sticky="e", pady=4)
    return row + 1


def build_updates_card(plugin, parent, row):
    card = make_card(parent, row)
    card.grid_columnconfigure(1, weight=1)

    customtkinter.CTkLabel(
        card, text="Signature Updates", font=font(14, bold=True),
    ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

    add_separator(card, 1)

    r = _build_db_info_rows(plugin, card, start_row=2)
    add_separator(card, r)
    r = _build_auto_update_toggle(plugin, card, r + 1)

    update_btn = customtkinter.CTkButton(
        card, text="Update Now", height=30, corner_radius=8,
        font=font(12), fg_color="transparent", border_width=1,
        border_color=COLOR_BTN_OUTLINE, text_color=COLOR_BTN_OUTLINE,
        hover_color=COLOR_BTN_OUTLINE_HOVER,
        command=lambda: plugin._on_action("update_sigs"),
    )
    update_btn.grid(
        row=r, column=0, columnspan=2, padx=16, pady=(8, 14), sticky="ew",
    )
    plugin._action_buttons["update_sigs"] = update_btn
    return row + 1
