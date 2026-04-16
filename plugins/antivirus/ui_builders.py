"""Primary UI builder functions for the Antivirus plugin.

Builds the Status Card, Scan Actions / Real-Time Protection,
and Scan Activity sections.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter

from plugins.antivirus.theme import (
    COLOR_CARD_BG,
    COLOR_CARD_BORDER,
    COLOR_MUTED,
    COLOR_WARN_BG,
    COLOR_WARN_TEXT,
    CORNER_R,
    PAD_X,
    font,
    make_card,
)


# ── 1. Protection Status Card (VPN-style) ──────────────


def build_status_banner(plugin, parent, row):
    """Build a VPN-style status card with title, subtitle, and action button."""
    bg = COLOR_WARN_BG

    card = customtkinter.CTkFrame(
        parent, fg_color=bg, corner_radius=CORNER_R, border_width=0,
    )
    card.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(16, 10))
    card.grid_columnconfigure(0, weight=1)

    text_col = customtkinter.CTkFrame(card, fg_color="transparent")
    text_col.grid(row=0, column=0, padx=22, pady=20, sticky="w")

    plugin._banner_label = customtkinter.CTkLabel(
        text_col, text="Checking...",
        font=customtkinter.CTkFont(family="Inter", size=28, weight="bold"),
        text_color=COLOR_WARN_TEXT,
    )
    plugin._banner_label.grid(row=0, column=0, sticky="w")

    plugin._banner_subtitle = customtkinter.CTkLabel(
        text_col, text="Checking protection status...",
        font=customtkinter.CTkFont(family="Inter", size=12),
        text_color=("#555555", "#AAAAAA"),
        wraplength=340, justify="left",
    )
    plugin._banner_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

    plugin._banner_action_btn = customtkinter.CTkButton(
        card, text="Open Settings", width=130, height=34,
        corner_radius=8,
        font=customtkinter.CTkFont(family="Inter", size=12, weight="bold"),
        command=lambda: None,
    )
    # Hidden initially — shown only when user action is needed
    plugin._banner_action_btn.grid(row=0, column=1, padx=22, pady=20)
    plugin._banner_action_btn.grid_remove()

    plugin._banner_progress = customtkinter.CTkProgressBar(
        card, height=4, mode="indeterminate",
    )
    plugin._banner_progress.grid(
        row=1, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="ew",
    )
    plugin._banner_progress.grid_remove()

    plugin._banner_frame = card
    return row + 1


# ── 2. Scan Actions + Real-Time Protection ───────────────


def _build_scan_card(plugin, container):
    card = customtkinter.CTkFrame(
        container, corner_radius=CORNER_R, fg_color=COLOR_CARD_BG,
        border_width=1, border_color=COLOR_CARD_BORDER,
    )
    card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
    card.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        card, text="Scan", font=font(14, bold=True),
    ).grid(row=0, column=0, padx=16, pady=(14, 10), sticky="w")

    actions = [
        ("Scan File", "scan_file"),
        ("Scan Directory", "scan_directory"),
    ]
    btn_frame = customtkinter.CTkFrame(card, fg_color="transparent")
    btn_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
    for i in range(len(actions)):
        btn_frame.grid_columnconfigure(i, weight=1)

    for col, (text, key) in enumerate(actions):
        btn = customtkinter.CTkButton(
            btn_frame, text=text, height=34, corner_radius=8,
            font=font(12),
            command=lambda k=key: plugin._on_action(k),
        )
        px = (0, 4) if col < len(actions) - 1 else (0, 0)
        btn.grid(row=0, column=col, padx=px, sticky="ew")
        plugin._action_buttons[key] = btn


def build_scan_and_protection(plugin, parent, row):
    container = customtkinter.CTkFrame(
        parent, fg_color="transparent", corner_radius=0,
    )
    container.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(0, 6))
    container.grid_columnconfigure(0, weight=1)

    _build_scan_card(plugin, container)
    return row + 1


# ── 3. Scan Activity ────────────────────────────────────


def build_scan_activity(plugin, parent, row):
    card = make_card(parent, row)
    card.grid_columnconfigure(0, weight=1)

    header = customtkinter.CTkFrame(card, fg_color="transparent")
    header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
    header.grid_columnconfigure(0, weight=1)

    customtkinter.CTkLabel(
        header, text="Scan Activity", font=font(14, bold=True),
    ).grid(row=0, column=0, sticky="w")

    plugin._scan_status_label = customtkinter.CTkLabel(
        header, text="No scans yet", font=font(11),
        text_color=COLOR_MUTED,
    )
    plugin._scan_status_label.grid(row=0, column=1, sticky="e")

    cancel_btn = customtkinter.CTkButton(
        header, text="Cancel", width=60, height=24, corner_radius=6,
        font=font(11), fg_color="transparent", border_width=1,
        border_color=("#DC2626", "#F87171"),
        text_color=("#DC2626", "#F87171"),
        hover_color=("#FEE2E2", "#3B1010"),
        command=plugin._cancel_scan,
    )
    cancel_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))
    cancel_btn.grid_remove()  # Hidden until a scan starts
    plugin._action_buttons["cancel_scan"] = cancel_btn

    plugin._scan_progress = customtkinter.CTkProgressBar(card, height=4)
    plugin._scan_progress.set(0)
    plugin._scan_progress.grid(
        row=1, column=0, padx=16, pady=(0, 2), sticky="ew",
    )
    plugin._scan_progress.grid_remove()

    plugin._scan_log = customtkinter.CTkTextbox(
        card, height=140, corner_radius=6,
        font=customtkinter.CTkFont(family="Courier New", size=11),
        state="disabled",
    )
    plugin._scan_log.grid(
        row=2, column=0, padx=16, pady=(4, 14), sticky="ew",
    )
    return row + 1
