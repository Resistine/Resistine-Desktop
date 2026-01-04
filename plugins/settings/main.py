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
import sys

import customtkinter

from plugins.base_plugin import BasePlugin
from utils import settings
from utils.i18n import get_text
from utils.logger import logger


class Plugin(BasePlugin):
    """Settings plugin (API key + appearance mode)."""

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

    def _effective_appearance_mode(self) -> str:
        mode = customtkinter.get_appearance_mode()
        if mode != "System":
            return mode

        if sys.platform == "darwin":
            try:
                import subprocess

                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True,
                    text=True,
                )
                return "Dark" if result.returncode == 0 and "Dark" in result.stdout else "Light"
            except Exception:
                return "Light"

        return "Light"

    def _apply_theme_refresh(self):
        # Prefer a lightweight refresh (no plugin re-instantiation)
        if hasattr(self.app, "refresh_ui_theme"):
            try:
                self.app.refresh_ui_theme()
                return
            except Exception as e:
                logger.error(f"Theme refresh failed: {e}")
                self.app.show_notification(f"Theme refresh failed: {e}", type="error")

        try:
            self.app.update_idletasks()
        except Exception:
            pass

    def create_main_screen(self):
        """Create a denser settings layout (UI_Dev-style cards) with less empty space."""
        # Scrollable so it never leaves a big blank panel on tall windows
        self.frame_5 = customtkinter.CTkScrollableFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.frame_5.grid_columnconfigure(0, weight=1)

        appearance_mode = self._effective_appearance_mode()
        panel_bg = "#1A1A1A" if appearance_mode == "Dark" else "#ffffff"
        text_color = "#ffffff" if appearance_mode == "Dark" else "#000000"

        # --- Profile card ---
        profile_card = customtkinter.CTkFrame(self.frame_5, corner_radius=12, fg_color=panel_bg)
        profile_card.grid(row=0, column=0, padx=20, pady=(16, 10), sticky="ew")
        profile_card.grid_columnconfigure(0, weight=1)

        profile_title = customtkinter.CTkLabel(
            profile_card,
            text="Profile",
            font=customtkinter.CTkFont(size=18, weight="bold"),
            text_color=text_color,
        )
        profile_title.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        email_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
            "utils",
            "email-settings.txt",
        )
        email = "Authenticated via API"
        if os.path.exists(email_file_path):
            try:
                with open(email_file_path, "r") as file:
                    email = file.read().strip() or email
            except Exception:
                pass

        customtkinter.CTkLabel(
            profile_card,
            text=f"Email: {email}",
            font=customtkinter.CTkFont(size=14),
            text_color=text_color,
        ).grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")

        # --- API key card ---
        api_card = customtkinter.CTkFrame(self.frame_5, corner_radius=12, fg_color=panel_bg)
        api_card.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        api_card.grid_columnconfigure(0, weight=1)

        api_title = customtkinter.CTkLabel(
            api_card,
            text=get_text("settings.apikey.label"),
            font=customtkinter.CTkFont(size=18, weight="bold"),
            text_color=text_color,
        )
        api_title.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        self.api_key_entry = customtkinter.CTkEntry(
            api_card,
            placeholder_text=get_text("settings.apikey.placeholder"),
            height=38,
            show="*",
        )
        self.api_key_entry.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")

        existing_key = settings.get_secret("chat", "openai_api_key")
        if existing_key:
            self.api_key_entry.insert(0, existing_key)

        btn_row = customtkinter.CTkFrame(api_card, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=0)
        btn_row.grid_columnconfigure(1, weight=1)

        self.save_key_button = customtkinter.CTkButton(
            btn_row,
            text=get_text("settings.apikey.save"),
            height=36,
            command=self.save_api_key,
        )
        self.save_key_button.grid(row=0, column=0, sticky="w")

        self.status_label = customtkinter.CTkLabel(
            btn_row,
            text="",
            font=customtkinter.CTkFont(size=12),
            text_color=text_color,
        )
        self.status_label.grid(row=0, column=1, padx=(12, 0), sticky="w")

        # --- Appearance card (System/Light/Dark only) ---
        appearance_card = customtkinter.CTkFrame(self.frame_5, corner_radius=12, fg_color=panel_bg)
        appearance_card.grid(row=2, column=0, padx=20, pady=(10, 16), sticky="ew")
        appearance_card.grid_columnconfigure(0, weight=1)

        appearance_title = customtkinter.CTkLabel(
            appearance_card,
            text="Appearance",
            font=customtkinter.CTkFont(size=18, weight="bold"),
            text_color=text_color,
        )
        appearance_title.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        customtkinter.CTkLabel(
            appearance_card,
            text="Mode:",
            font=customtkinter.CTkFont(size=14),
            text_color=text_color,
        ).grid(row=1, column=0, padx=16, pady=(0, 6), sticky="w")

        self.appearance_mode_var = customtkinter.StringVar(value=customtkinter.get_appearance_mode())
        appearance_menu = customtkinter.CTkOptionMenu(
            appearance_card,
            values=["System", "Light", "Dark"],
            variable=self.appearance_mode_var,
            command=self.change_appearance_mode,
            height=38,
        )
        appearance_menu.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")

        return self.frame_5

    def save_api_key(self):
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            return

        success = settings.set_secret("chat", "openai_api_key", api_key)
        if success:
            self.status_label.configure(text=get_text("settings.apikey.saved_success"), text_color="green")

            # Reinitialize the chat plugin's OpenAI client if it's loaded
            if hasattr(self.app, "plugin_list"):
                for plugin in self.app.plugin_list:
                    if plugin.get_name() == "Chat" and hasattr(plugin, "reinitialize_client"):
                        plugin.reinitialize_client()
                        break

            self.app.after(2500, lambda: self.status_label.configure(text=""))
        else:
            self.status_label.configure(text=get_text("settings.apikey.saved_error"), text_color="red")

    def change_appearance_mode(self, new_appearance_mode: str):
        try:
            customtkinter.set_appearance_mode(new_appearance_mode)
        finally:
            self._apply_theme_refresh()
