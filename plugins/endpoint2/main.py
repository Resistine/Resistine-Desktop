"""
Endpoint 2 Plugin (placeholder)
A second Endpoint sidebar entry with an empty page, used as a starting point
for a new endpoint-page architecture.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter

from plugins.base_plugin import BasePlugin

_WAZUH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "wazuh")


class Plugin(BasePlugin):
    """Placeholder Endpoint plugin shown directly below the existing Endpoint entry."""

    def __init__(self, app):
        super().__init__(
            id="013",
            version="2026.01.04-alpha",
            order=5.5,
            name="Endpoint 2",
            status=None,
            description="Placeholder for the redesigned endpoint page.",
            supported_systems=["Darwin", "Linux", "Windows"],
            translations={"US": "Endpoint 2", "ES": "Endpoint 2", "FR": "Endpoint 2"},
            icon_light_path=os.path.join(_WAZUH_DIR, "add_user_light.png"),
            icon_dark_path=os.path.join(_WAZUH_DIR, "add_user_dark.png"),
            uninstall_enabled=True,
        )
        self.app = app

    def check_status(self):
        return None

    def create_main_screen(self):
        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)
        return self.main_container
