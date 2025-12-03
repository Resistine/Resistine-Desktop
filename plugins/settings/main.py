## @file plugins/settings/main.py
## @package settings_plugin
## @namespace settings_plugin
## @class settings_plugin::Plugin

"""
This file contains the main plugin class for the Settings plugin.
The plugin allows users to configure their account settings.
Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter

from plugins.base_plugin import BasePlugin
from utils import settings
from utils.i18n import get_text


class Plugin(BasePlugin):
    """
    @brief Plugin class for the Settings plugin.
    Plugin class for the Settings plugin, that allows user to configure their account settings.
    """

    def __init__(self, app):
        """
        @brief Initialize the Settings plugin.
        Initialize the Settings plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="010",
            order=10,
            name="Settings",
            status="OK",
            description="This plugin allows you to configure your account settings.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Settings", "ES": "Configuracion", "FR": "Paramètres"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "settings_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "settings_dark.png"
            ),
        )
        self.app = app

    def create_main_screen(self):
        """
        @brief Create the main screen for the Settings plugin.
        Create the main screen for the Settings plugin.
        """
        self.frame_5 = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.frame_5.grid_columnconfigure(0, weight=1)
        # Add more rows for API key settings
        self.frame_5.grid_rowconfigure((0, 1, 2, 3, 4, 5), weight=0)

        # --- Profile Section ---
        self.profile_name_label = customtkinter.CTkLabel(
            self.frame_5, text="Name: ", font=customtkinter.CTkFont(size=20)
        )
        self.profile_name_label.grid(
            row=0, column=0, padx=20, pady=(20, 10), sticky="w"
        )

        # Try to read email from file, but handle case where it doesn't exist (API-based auth)
        email_file_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
            ),
            "utils",
            "email-settings.txt",
        )
        email = "Not set"
        if os.path.exists(email_file_path):
            try:
                with open(email_file_path, "r") as file:
                    email = file.read().strip()
            except Exception as e:
                print(f"Error reading email settings: {e}")
                email = "Not available"
        else:
            # Email is stored via API authentication, not in local file
            email = "Authenticated via API"

        self.profile_email_label = customtkinter.CTkLabel(
            self.frame_5, text=f"Email: {email}", font=customtkinter.CTkFont(size=20)
        )
        self.profile_email_label.grid(row=1, column=0, padx=20, pady=10, sticky="w")

        # --- Separator ---
        separator = customtkinter.CTkFrame(self.frame_5, height=2, fg_color="gray50")
        separator.grid(row=2, column=0, padx=20, pady=20, sticky="ew")

        # --- OpenAI API Key Section ---
        self.api_key_label = customtkinter.CTkLabel(
            self.frame_5,
            text=get_text("settings.apikey.label"),
            font=customtkinter.CTkFont(size=16, weight="bold"),
        )
        self.api_key_label.grid(row=3, column=0, padx=20, pady=(10, 5), sticky="w")

        self.api_key_entry = customtkinter.CTkEntry(
            self.frame_5,
            placeholder_text=get_text("settings.apikey.placeholder"),
            width=400,
            show="*",  # Mask the key
        )
        self.api_key_entry.grid(row=4, column=0, padx=20, pady=5, sticky="w")

        # Pre-fill existing key if available
        existing_key = settings.get_secret("chat", "openai_api_key")
        if existing_key:
            self.api_key_entry.insert(0, existing_key)

        self.save_key_button = customtkinter.CTkButton(
            self.frame_5,
            text=get_text("settings.apikey.save"),
            command=self.save_api_key,
        )
        self.save_key_button.grid(row=5, column=0, padx=20, pady=10, sticky="w")

        self.status_label = customtkinter.CTkLabel(
            self.frame_5, text="", font=customtkinter.CTkFont(size=12)
        )
        self.status_label.grid(row=6, column=0, padx=20, pady=5, sticky="w")

        return self.frame_5

    def save_api_key(self):
        """Save the OpenAI API key securely."""
        api_key = self.api_key_entry.get().strip()

        if not api_key:
            # If empty, maybe clear it? For now just return
            return

        success = settings.set_secret("chat", "openai_api_key", api_key)

        if success:
            self.status_label.configure(
                text=get_text("settings.apikey.saved_success"), text_color="green"
            )

            # Reinitialize the chat plugin's OpenAI client if it's loaded
            if hasattr(self.app, "plugin_list"):
                for plugin in self.app.plugin_list:
                    if plugin.get_name() == "Chat" and hasattr(
                        plugin, "reinitialize_client"
                    ):
                        plugin.reinitialize_client()
                        print("Chat plugin reinitialized with new API key")
                        break

            # Clear status after 3 seconds
            self.app.after(3000, lambda: self.status_label.configure(text=""))
        else:
            self.status_label.configure(
                text=get_text("settings.apikey.saved_error"), text_color="red"
            )
