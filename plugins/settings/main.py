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
    """Settings plugin (API key + theme controls)."""

    def __init__(self, app):
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

    def _apply_theme_refresh(self):
        # Prefer a lightweight refresh (no plugin re-instantiation)
        if hasattr(self.app, "refresh_ui_theme"):
            try:
                self.app.refresh_ui_theme()
                return
            except Exception as e:
                print(f"Theme refresh failed: {e}")

        # Fallback: at least force a repaint
        try:
            self.app.update_idletasks()
        except Exception:
            pass

    def create_main_screen(self):
        self.frame_5 = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.frame_5.grid_columnconfigure(0, weight=1)
        self.frame_5.grid_rowconfigure(tuple(range(0, 20)), weight=0)

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
            show="*",
        )
        self.api_key_entry.grid(row=4, column=0, padx=20, pady=5, sticky="w")

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

        # --- Separator (Theme) ---
        separator2 = customtkinter.CTkFrame(self.frame_5, height=2, fg_color="gray50")
        separator2.grid(row=7, column=0, padx=20, pady=20, sticky="ew")

        # --- Appearance / Theme Section ---
        appearance_title = customtkinter.CTkLabel(
            self.frame_5,
            text="Appearance",
            font=customtkinter.CTkFont(size=16, weight="bold"),
        )
        appearance_title.grid(row=8, column=0, padx=20, pady=(0, 10), sticky="w")

        appearance_label = customtkinter.CTkLabel(
            self.frame_5,
            text="Appearance Mode:",
            font=customtkinter.CTkFont(size=14),
        )
        appearance_label.grid(row=9, column=0, padx=20, pady=(0, 5), sticky="w")

        self.appearance_mode_var = customtkinter.StringVar(
            value=customtkinter.get_appearance_mode()
        )
        appearance_menu = customtkinter.CTkOptionMenu(
            self.frame_5,
            values=["Light", "Dark", "System"],
            variable=self.appearance_mode_var,
            command=self.change_appearance_mode,
            width=240,
        )
        appearance_menu.grid(row=10, column=0, padx=20, pady=(0, 15), sticky="w")

        return self.frame_5

    def save_api_key(self):
        """Save the OpenAI API key securely."""
        api_key = self.api_key_entry.get().strip()

        if not api_key:
            return

        success = settings.set_secret("chat", "openai_api_key", api_key)

        if success:
            self.status_label.configure(
                text=get_text("settings.apikey.saved_success"), text_color="green"
            )

            # Reinitialize the chat plugin's OpenAI client if it's loaded
            if hasattr(self.app, "plugin_list"):
                for plugin in self.app.plugin_list:
                    if plugin.get_name() == "Chat" and hasattr(plugin, "reinitialize_client"):
                        plugin.reinitialize_client()
                        print("Chat plugin reinitialized with new API key")
                        break

            self.app.after(3000, lambda: self.status_label.configure(text=""))
        else:
            self.status_label.configure(
                text=get_text("settings.apikey.saved_error"), text_color="red"
            )

    def change_appearance_mode(self, new_appearance_mode: str):
        """Change Light/Dark/System appearance."""
        try:
            customtkinter.set_appearance_mode(new_appearance_mode)
        finally:
            self._apply_theme_refresh()

