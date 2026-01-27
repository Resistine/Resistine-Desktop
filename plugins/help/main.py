## @file main.py
## @namespace plugins.help
"""
This plugin provides help documentation.
Author: Petr and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter

from plugins.base_plugin import BasePlugin

from .markdown_viewer import MarkdownViewer


class Plugin(BasePlugin):
    """
    @brief Plugin class for the Help plugin.
    Plugin class for the Help plugin, that provides help documentation.
    """

    def __init__(self, app):
        """
        @brief Initialize the Help plugin.
        Initialize the Help plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="009",
            version="2025.01.01",
            order=200,
            name="Help",
            status=None,
            description="This plugin provides help documentation.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Help", "ES": "Ayuda", "FR": "Aide"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "help_light.svg"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "help_dark.svg"
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
        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color=("#f0eff6", "#1a1a1a")
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        # Path to docs directory
        current_dir = os.path.dirname(os.path.realpath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        docs_dir = os.path.join(project_root, "docs")
        help_file_path = os.path.join(docs_dir, "Help.md")

        self.viewer = MarkdownViewer(self.main_container, docs_dir=docs_dir)
        self.viewer.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)

        self.viewer.load_file(help_file_path)

        return self.main_container
