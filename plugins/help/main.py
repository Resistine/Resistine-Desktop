## @file main.py
## @namespace plugins.help
"""
This plugin provides help documentation.
Author: Petr and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import sys

import customtkinter

from plugins.base_plugin import BasePlugin

from .markdown_viewer import MarkdownViewer


def _resource_path(relative_path: str) -> str:
    """Resolve path for both dev and PyInstaller bundles."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        relative_path,
    )


class Plugin(BasePlugin):
    """
    @brief Plugin class for the Help plugin.
    Plugin class for the Help plugin, that provides help documentation.
    """

    # Help renders markdown via MarkdownBubble (self-resizes via after() timers,
    # same as Chat), so its layout settles asynchronously after build. Defer the
    # swap until it's quiescent so switching to Help doesn't tear/reflow.
    defer_reveal_until_settled = True

    def __init__(self, app):
        """
        @brief Initialize the Help plugin.
        Initialize the Help plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="009",
            version="2025.01.01",
            order=1010,
            name="Help",
            status=None,
            description="This plugin provides help documentation.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Help", "ES": "Ayuda", "FR": "Aide"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "help_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "help_dark.png"
            ),
            uninstall_enabled=False,
        )
        self.app = app
        self.status = self.get_status()

    def create_main_screen(self):
        """
        @brief Create the main screen for the Help plugin.
        Create the main screen for the Help plugin.
        """
        self.main_container = customtkinter.CTkScrollableFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.main_container.grid_columnconfigure(0, weight=1)

        docs_dir = _resource_path("docs")
        help_file_path = os.path.join(docs_dir, "Help.md")

        self.viewer = MarkdownViewer(self.main_container, docs_dir=docs_dir)
        self.viewer.pack(fill="both", expand=True, padx=20, pady=(16, 20))

        self.viewer.load_file(help_file_path)

        return self.main_container
