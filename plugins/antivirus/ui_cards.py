"""Secondary UI card builders for the Antivirus plugin.

Builds the Whitelist/Quarantine and Signature Updates sections.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter
from customtkinter import ThemeManager

from plugins.antivirus.theme import (
    COLOR_BTN_OUTLINE,
    COLOR_BTN_OUTLINE_HOVER,
    COLOR_CARD_BG,
    COLOR_CARD_BORDER,
    COLOR_MUTED,
    COLOR_OK_TEXT,
    CORNER_R,
    PAD_X,
    add_separator,
    font,
    make_card,
    section_title,
)


def _muted():
    return ThemeManager.theme.get("Theme", {}).get("text_secondary")


def _btn_border():
    return ThemeManager.theme.get("CTkButton", {}).get("border_color")


def _btn_hover():
    return ThemeManager.theme.get("CTkButton", {}).get("hover_color")


# ── 4. Whitelist + Quarantine ────────────────────────────


def _build_whitelist_card(plugin, container):
    card = customtkinter.CTkFrame(
        container, corner_radius=CORNER_R, border_width=1,
    )
    card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
    card.grid_columnconfigure(0, weight=1)

    hdr = customtkinter.CTkFrame(card, fg_color="transparent")
    hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 3))
    hdr.grid_columnconfigure(0, weight=1)

    section_title(hdr, "Whitelist").grid(row=0, column=0, sticky="w")

    customtkinter.CTkButton(
        hdr, text="+ Add", width=60, height=26, corner_radius=6,
        font=font(11), fg_color="transparent", border_width=1,
        border_color=_btn_border(), text_color=_btn_border(),
        hover_color=_btn_hover(),
        command=lambda: plugin._on_action("whitelist_add"),
    ).grid(row=0, column=1, sticky="e")

    add_separator(card, 1)

    plugin._whitelist_frame = customtkinter.CTkFrame(
        card, fg_color="transparent",
    )
    plugin._whitelist_frame.grid(
        row=2, column=0, padx=16, pady=(8, 14), sticky="ew",
    )
    plugin._whitelist_frame.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        plugin._whitelist_frame, text="No whitelisted paths",
        font=font(12), text_color=_muted(),
    ).grid(row=0, column=0, sticky="w")


def _build_quarantine_card(plugin, container):
    card = customtkinter.CTkFrame(
        container, corner_radius=CORNER_R, border_width=1,
    )
    card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
    card.grid_columnconfigure(0, weight=1)

    section_title(card, "Quarantine").grid(
        row=0, column=0, padx=16, pady=(14, 3), sticky="w",
    )
    add_separator(card, 1)

    plugin._quarantine_frame = customtkinter.CTkFrame(
        card, fg_color="transparent",
    )
    plugin._quarantine_frame.grid(
        row=2, column=0, padx=16, pady=(8, 14), sticky="ew",
    )
    plugin._quarantine_frame.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        plugin._quarantine_frame, text="No threats quarantined",
        font=font(12), text_color=_muted(),
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


# ── 5. Scan Exclusions ─────────────────────────────────


def build_scan_exclusions(plugin, parent, row):
    """Build the Scan Exclusions card (extension filter + max file size)."""
    card = make_card(parent, row)
    card.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        card, text="Scan Exclusions", font=font(14, bold=True),
    ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

    add_separator(card, 1)

    # ── Extension exclusions ──
    customtkinter.CTkLabel(
        card, text="Skip File Extensions", font=font(12),
        text_color=COLOR_MUTED,
    ).grid(row=2, column=0, columnspan=2, padx=16, pady=(8, 4), sticky="w")

    add_row = customtkinter.CTkFrame(card, fg_color="transparent")
    add_row.grid(
        row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4),
    )
    add_row.grid_columnconfigure(0, weight=1)

    plugin._ext_entry = customtkinter.CTkEntry(
        add_row, height=28, placeholder_text=".iso, .vmdk, .log",
        font=font(11),
    )
    plugin._ext_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    plugin._ext_entry.bind("<Return>", lambda e: plugin._add_excluded_extension())

    customtkinter.CTkButton(
        add_row, text="+ Add", width=60, height=28, corner_radius=6,
        font=font(11), fg_color="transparent", border_width=1,
        border_color=COLOR_BTN_OUTLINE, text_color=COLOR_BTN_OUTLINE,
        hover_color=COLOR_BTN_OUTLINE_HOVER,
        command=plugin._add_excluded_extension,
    ).grid(row=0, column=1)

    plugin._exclusions_frame = customtkinter.CTkFrame(
        card, fg_color="transparent",
    )
    plugin._exclusions_frame.grid(
        row=4, column=0, columnspan=2, padx=16, pady=(0, 8), sticky="ew",
    )
    plugin._exclusions_frame.grid_columnconfigure(0, weight=1)

    add_separator(card, 5)

    # ── Max file size ──
    size_row = customtkinter.CTkFrame(card, fg_color="transparent")
    size_row.grid(
        row=6, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 14),
    )
    size_row.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        size_row, text="Max File Size", font=font(12),
    ).grid(row=0, column=0, sticky="w")

    right = customtkinter.CTkFrame(size_row, fg_color="transparent")
    right.grid(row=0, column=1, sticky="e")

    plugin._size_entry = customtkinter.CTkEntry(
        right, width=70, height=28, font=font(11), justify="right",
    )
    plugin._size_entry.grid(row=0, column=0)
    plugin._size_entry.insert(0, "0")
    plugin._size_entry.bind("<Return>", lambda e: plugin._save_max_file_size())
    plugin._size_entry.bind("<FocusOut>", lambda e: plugin._save_max_file_size())

    customtkinter.CTkLabel(
        right, text="MB", font=font(11), text_color=COLOR_MUTED,
    ).grid(row=0, column=1, padx=(4, 0))

    customtkinter.CTkLabel(
        size_row, text="0 = no limit",
        font=font(10), text_color=COLOR_MUTED,
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

    return row + 1


# ── 6. Signature Updates ────────────────────────────────


# (build_updates_card defined below)


# ── 7. SIEM Forwarding ─────────────────────────────────


def build_siem_card(plugin, parent, row):
    """Build the SIEM Forwarding card (threat log + Wazuh setup)."""
    from plugins.antivirus.threat_log import get_log_path, is_wazuh_installed

    card = make_card(parent, row)
    card.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        card, text="SIEM Forwarding", font=font(14, bold=True),
    ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

    add_separator(card, 1)

    # Threat log path
    customtkinter.CTkLabel(
        card, text="Threat Log", text_color=COLOR_MUTED, font=font(12),
    ).grid(row=2, column=0, padx=16, pady=(8, 0), sticky="w")

    customtkinter.CTkLabel(
        card, text=get_log_path(), font=font(10),
        text_color=COLOR_MUTED, wraplength=340, justify="left",
    ).grid(row=3, column=0, columnspan=2, padx=16, pady=(2, 8), sticky="w")

    add_separator(card, 4)

    if is_wazuh_installed():
        plugin._siem_status_label = customtkinter.CTkLabel(
            card, text="Wazuh agent detected",
            font=font(12), text_color=COLOR_OK_TEXT,
        )
        plugin._siem_status_label.grid(
            row=5, column=0, padx=16, pady=(8, 4), sticky="w",
        )

        plugin._siem_btn = customtkinter.CTkButton(
            card, text="Configure Forwarding", height=30,
            corner_radius=8, font=font(12),
            fg_color="transparent", border_width=1,
            border_color=COLOR_BTN_OUTLINE,
            text_color=COLOR_BTN_OUTLINE,
            hover_color=COLOR_BTN_OUTLINE_HOVER,
            command=plugin._setup_wazuh_forwarding,
        )
        plugin._siem_btn.grid(
            row=6, column=0, columnspan=2,
            padx=16, pady=(4, 14), sticky="ew",
        )
    else:
        customtkinter.CTkLabel(
            card, text="Wazuh agent not installed",
            font=font(12), text_color=COLOR_MUTED,
        ).grid(row=5, column=0, padx=16, pady=(8, 4), sticky="w")

        customtkinter.CTkLabel(
            card, text="Threat events are logged locally.",
            font=font(11), text_color=COLOR_MUTED,
        ).grid(row=6, column=0, padx=16, pady=(0, 14), sticky="w")

    return row + 1


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
            card, text=label, text_color=_muted(), font=font(12),
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
        font=font(11), text_color=_muted(),
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

    section_title(card, "Signature Updates").grid(
        row=0, column=0, columnspan=2, padx=16, pady=(14, 3), sticky="w",
    )

    add_separator(card, 1)

    r = _build_db_info_rows(plugin, card, start_row=2)
    add_separator(card, r)
    r = _build_auto_update_toggle(plugin, card, r + 1)

    update_btn = customtkinter.CTkButton(
        card, text="Update Now", height=30, corner_radius=8,
        font=font(12), fg_color="transparent", border_width=1,
        border_color=_btn_border(), text_color=_btn_border(),
        hover_color=_btn_hover(),
        command=lambda: plugin._on_action("update_sigs"),
    )
    update_btn.grid(
        row=r, column=0, columnspan=2, padx=16, pady=(8, 14), sticky="ew",
    )
    plugin._action_buttons["update_sigs"] = update_btn
    return row + 1
