"""Antivirus plugin UI for Resistine Desktop.

Pure UI layout — all backend functionality (ClamAV scanning, clamonacc,
freshclam, quarantine) will be integrated separately via ClamAV-Mac.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter

from plugins.antivirus.theme import (
    COLOR_OK_BG,
    COLOR_OK_TEXT,
    COLOR_WARN_BG,
    COLOR_WARN_TEXT,
)
from plugins.antivirus.ui_builders import (
    build_scan_activity,
    build_scan_and_protection,
    build_status_banner,
)
from plugins.antivirus.ui_cards import (
    build_updates_card,
    build_whitelist_and_quarantine,
)
from plugins.base_plugin import BasePlugin
from utils.logger import logger

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))


class Plugin(BasePlugin):
    """Antivirus plugin powered by ClamAV."""

    def __init__(self, app):
        super().__init__(
            id="012",
            version="2026.01.04-alpha",
            order=6,
            name="Antivirus",
            status=None,
            description="Scan, quarantine, and protect against malware with ClamAV.",
            supported_systems=["Darwin"],
            translations={"US": "Antivirus", "ES": "Antivirus", "FR": "Antivirus"},
            icon_light_path=os.path.join(_PLUGIN_DIR, "antivirus_light.png"),
            icon_dark_path=os.path.join(_PLUGIN_DIR, "antivirus_dark.png"),
            uninstall_enabled=True,
        )
        self.app = app
        self._realtime_on = False
        self._auto_update_on = True
        self._action_buttons = {}
        self._banner_frame = None
        self._banner_label = None
        self._rt_status = None
        self._rt_switch = None
        self.status = self.get_status()

    def check_status(self):
        if self._realtime_on:
            return "OK"
        return "Warning"

    # ── Main screen ──────────────────────────────────────────

    def create_main_screen(self):
        self.main_frame = customtkinter.CTkScrollableFrame(
            self.app, corner_radius=0, fg_color="transparent",
        )
        self.main_frame.grid_columnconfigure(0, weight=1)

        row = 0
        row = build_status_banner(self, self.main_frame, row)
        row = build_scan_and_protection(self, self.main_frame, row)
        row = build_scan_activity(self, self.main_frame, row)
        row = build_whitelist_and_quarantine(self, self.main_frame, row)
        row = build_updates_card(self, self.main_frame, row)

        customtkinter.CTkLabel(
            self.main_frame, text="", height=12,
        ).grid(row=row, column=0)
        return self.main_frame

    def destroy(self):
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.destroy()

    # ── UI Event Handlers ────────────────────────────────────

    def _update_banner(self):
        if self._banner_frame is None:
            return
        if self._realtime_on:
            self._banner_frame.configure(fg_color=COLOR_OK_BG)
            self._banner_label.configure(
                text="\u2713  Protected", text_color=COLOR_OK_TEXT,
            )
        else:
            self._banner_frame.configure(fg_color=COLOR_WARN_BG)
            self._banner_label.configure(
                text="\u26A0  Protection Off", text_color=COLOR_WARN_TEXT,
            )

    def _toggle_realtime(self):
        self._realtime_on = self._rt_switch.get()
        self._rt_status.configure(
            text="Active" if self._realtime_on else "Inactive",
        )
        self._update_banner()
        self.status = self.check_status()
        logger.info(
            f"Antivirus: real-time toggled "
            f"{'on' if self._realtime_on else 'off'}",
        )

    def _toggle_auto_update(self):
        self._auto_update_on = self._auto_update_switch.get()
        logger.info(
            f"Antivirus: auto-update toggled "
            f"{'on' if self._auto_update_on else 'off'}",
        )

    def _on_action(self, action_key: str):
        logger.info(f"Antivirus: action triggered — {action_key}")
