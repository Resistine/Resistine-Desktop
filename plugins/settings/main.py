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
            version="2025.01.01",
            order=1020,
            name="Settings",
            status=None,
            description="This plugin allows you to configure your account settings.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Settings", "ES": "Configuracion", "FR": "Paramètres"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "settings_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "settings_dark.png"
            ),
            uninstall_enabled=False,
        )
        self.app = app
        self.status = self.get_status()

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
                return (
                    "Dark"
                    if result.returncode == 0 and "Dark" in result.stdout
                    else "Light"
                )
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
        from customtkinter import ThemeManager

        # Scrollable so it never leaves a big blank panel on tall windows
        self.frame_5 = customtkinter.CTkScrollableFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.frame_5.grid_columnconfigure(0, weight=1)

        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 12)
        text_secondary = ThemeManager.theme.get("Theme", {}).get(
            "text_secondary", ["#6B7280", "#9CA3AF"]
        )
        divider_color = ThemeManager.theme.get("Theme", {}).get(
            "divider_color", ["#E5E7EB", "#2A2A2A"]
        )

        # ------------------------------------------------------------------ #
        #  Helper: section title with divider                                 #
        # ------------------------------------------------------------------ #
        def _section_title(parent, text, row):
            lbl = customtkinter.CTkLabel(
                parent,
                text=text,
                font=customtkinter.CTkFont(size=16, weight="bold"),
            )
            lbl.grid(row=row, column=0, padx=16, pady=(16, 0), sticky="w")
            div = customtkinter.CTkFrame(parent, height=1, fg_color=divider_color)
            div.grid(row=row + 1, column=0, padx=16, pady=(8, 12), sticky="ew")

        # --- Profile card ---
        profile_card = customtkinter.CTkFrame(self.frame_5, corner_radius=corner_radius)
        profile_card.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="ew")
        profile_card.grid_columnconfigure(0, weight=1)

        _section_title(profile_card, "Profile", 0)

        email = settings.get("auth", "email", "None")

        customtkinter.CTkLabel(
            profile_card,
            text=f"Email: {email}",
            font=customtkinter.CTkFont(size=13),
            text_color=text_secondary,
        ).grid(row=2, column=0, padx=16, pady=(0, 10), sticky="w")

        # Load sign-out icon
        signout_icon = None
        try:
            from PIL import Image
            plugin_dir = os.path.dirname(os.path.realpath(__file__))
            signout_light = Image.open(os.path.join(plugin_dir, "signout_light.png"))
            signout_dark = Image.open(os.path.join(plugin_dir, "signout_dark.png"))
            signout_icon = customtkinter.CTkImage(
                light_image=signout_light, dark_image=signout_dark, size=(18, 18)
            )
        except Exception:
            pass

        self.logout_button = customtkinter.CTkButton(
            profile_card,
            text="Log Out",
            image=signout_icon,
            compound="left",
            height=34,
            corner_radius=8,
            fg_color="#DC3545",
            hover_color="#C82333",
            command=self._handle_logout,
        )
        self.logout_button.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="w")

        # --- API key card ---
        api_card = customtkinter.CTkFrame(self.frame_5, corner_radius=corner_radius)
        api_card.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        api_card.grid_columnconfigure(0, weight=1)

        _section_title(api_card, get_text("settings.apikey.label"), 0)

        self.api_key_entry = customtkinter.CTkEntry(
            api_card,
            placeholder_text=get_text("settings.apikey.placeholder"),
            height=36,
            show="*",
        )
        self.api_key_entry.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="ew")

        customtkinter.CTkLabel(
            api_card,
            text=get_text("settings.apibase.label"),
            font=customtkinter.CTkFont(size=13),
            text_color=text_secondary,
        ).grid(row=3, column=0, padx=16, pady=(2, 4), sticky="w")

        self.api_base_entry = customtkinter.CTkEntry(
            api_card,
            placeholder_text=get_text("settings.apibase.placeholder"),
            height=36,
        )
        self.api_base_entry.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="ew")

        existing_key = settings.get_secret("chat", "openai_api_key")
        if existing_key:
            self.api_key_entry.insert(0, existing_key)

        existing_base = settings.get("chat", "openai_base_url")
        if existing_base:
            self.api_base_entry.insert(0, existing_base)

        # Disable Typing Animation Checkbox
        self.disable_animation_var = customtkinter.BooleanVar(
            value=settings.get("chat", "disable_animation", False)
        )
        self.disable_animation_checkbox = customtkinter.CTkCheckBox(
            api_card,
            text=get_text("settings.chat.disable_animation"),
            variable=self.disable_animation_var,
            onvalue=True,
            offvalue=False,
            command=self.save_animation_setting,
        )
        self.disable_animation_checkbox.grid(
            row=5, column=0, padx=16, pady=(0, 10), sticky="w"
        )

        btn_row = customtkinter.CTkFrame(api_card, fg_color="transparent")
        btn_row.grid(row=6, column=0, padx=16, pady=(0, 16), sticky="ew")
        btn_row.grid_columnconfigure(0, weight=0)
        btn_row.grid_columnconfigure(1, weight=1)

        self.save_key_button = customtkinter.CTkButton(
            btn_row,
            text=get_text("settings.apikey.save"),
            height=34,
            corner_radius=8,
            command=self.save_api_key,
        )
        self.save_key_button.grid(row=0, column=0, sticky="w")

        self.status_label = customtkinter.CTkLabel(
            btn_row,
            text="",
            font=customtkinter.CTkFont(size=12),
        )
        self.status_label.grid(row=0, column=1, padx=(12, 0), sticky="w")

        # --- Appearance card (System/Light/Dark only) ---
        appearance_card = customtkinter.CTkFrame(self.frame_5, corner_radius=corner_radius)
        appearance_card.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        appearance_card.grid_columnconfigure(0, weight=1)

        _section_title(appearance_card, "Appearance", 0)

        customtkinter.CTkLabel(
            appearance_card,
            text="Mode:",
            font=customtkinter.CTkFont(size=13),
            text_color=text_secondary,
        ).grid(row=2, column=0, padx=16, pady=(0, 4), sticky="w")

        self.appearance_mode_var = customtkinter.StringVar(
            value=customtkinter.get_appearance_mode()
        )
        appearance_menu = customtkinter.CTkOptionMenu(
            appearance_card,
            values=["System", "Light", "Dark"],
            variable=self.appearance_mode_var,
            command=self.change_appearance_mode,
            height=36,
            corner_radius=8,
        )
        appearance_menu.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="ew")

        # --- Software Updates card ---
        updates_card = customtkinter.CTkFrame(self.frame_5, corner_radius=corner_radius)
        updates_card.grid(row=3, column=0, padx=20, pady=8, sticky="ew")
        updates_card.grid_columnconfigure(0, weight=1)

        _section_title(updates_card, "Software Updates", 0)

        customtkinter.CTkLabel(
            updates_card,
            text=f"Current version: {self._get_app_version()}",
            font=customtkinter.CTkFont(size=13),
            text_color=text_secondary,
        ).grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")

        self.update_status_label = customtkinter.CTkLabel(
            updates_card,
            text="",
            font=customtkinter.CTkFont(size=12),
        )

        check_btn = customtkinter.CTkButton(
            updates_card,
            text="Check for Updates",
            height=34,
            corner_radius=8,
            command=self._check_for_updates,
        )
        check_btn.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="w")
        self.update_status_label.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="w")

        # --- Uninstall card ---
        uninstall_card = customtkinter.CTkFrame(self.frame_5, corner_radius=corner_radius)
        uninstall_card.grid(row=4, column=0, padx=20, pady=(8, 20), sticky="ew")
        uninstall_card.grid_columnconfigure(0, weight=1)

        _section_title(uninstall_card, "Uninstall", 0)

        customtkinter.CTkLabel(
            uninstall_card,
            text="Permanently remove Resistine and all associated data from this computer.",
            font=customtkinter.CTkFont(size=13),
            text_color=text_secondary,
            wraplength=500,
            justify="left",
        ).grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")

        self.uninstall_status_label = customtkinter.CTkLabel(
            uninstall_card,
            text="",
            font=customtkinter.CTkFont(size=12),
        )

        self.uninstall_button = customtkinter.CTkButton(
            uninstall_card,
            text="Uninstall Resistine",
            height=34,
            corner_radius=8,
            fg_color="#DC3545",
            hover_color="#C82333",
            command=self._handle_uninstall,
        )
        self.uninstall_button.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="w")
        self.uninstall_status_label.grid(row=4, column=0, padx=16, pady=(0, 16), sticky="w")

        return self.frame_5

    def save_animation_setting(self):
        """Save the disable animation setting."""
        disable = self.disable_animation_var.get()
        settings.set("chat", "disable_animation", disable)

    def save_api_key(self):
        api_key = self.api_key_entry.get().strip()
        api_base = self.api_base_entry.get().strip()

        if not api_key:
            return

        success_key = settings.set_secret("chat", "openai_api_key", api_key)
        # Always set/update base_url, even if empty (to allow clearing it)
        success_base = settings.set(
            "chat", "openai_base_url", api_base if api_base else None
        )

        if success_key and success_base:
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
                        break

            self.app.after(2500, lambda: self.status_label.configure(text=""))
        else:
            self.status_label.configure(
                text=get_text("settings.apikey.saved_error"), text_color="red"
            )

    def _get_app_version(self):
        """Read the app version from Info.plist (macOS frozen) or Resistine.spec (source)."""
        try:
            if getattr(sys, "frozen", False):
                import plistlib

                contents_dir = os.path.dirname(os.path.dirname(sys.executable))
                plist_path = os.path.join(contents_dir, "Info.plist")
                if os.path.exists(plist_path):
                    with open(plist_path, "rb") as f:
                        info = plistlib.load(f)
                    return info.get("CFBundleShortVersionString", "1.0.0")
        except Exception:
            pass

        # Running from source (Linux, dev mode): read from spec file
        try:
            from utils.updates.version import get_current_version
            version = get_current_version()
            if version != "0.0.0":
                return version
        except Exception:
            pass

        return "1.0.0"

    def _check_for_updates(self):
        """Trigger an interactive update check via the cross-platform update manager.

        On macOS (Sparkle) and Windows (WinSparkle) the native library shows
        its own progress/result UI.  On Linux, the Python updater shows its
        own dialogs.  The status label below the button is a lightweight
        fallback for edge cases (updater unavailable, errors).
        """
        try:
            from utils import updates

            if not updates.is_available():
                self.update_status_label.configure(
                    text="Updates not available in this build", text_color="orange"
                )
                self.app.after(5000, lambda: self.update_status_label.configure(text=""))
                return

            self.update_status_label.configure(
                text="Checking for updates...", text_color="green"
            )

            result = updates.check_for_updates()

            if result == "error":
                self.update_status_label.configure(
                    text="Update check failed", text_color="red"
                )
            else:
                # Native Sparkle/WinSparkle UI handles "up to date" and
                # "update available" popups.  Clear the status label.
                self.app.after(3000, lambda: self.update_status_label.configure(text=""))
                return

            self.app.after(5000, lambda: self.update_status_label.configure(text=""))
        except Exception as e:
            logger.error(f"Update check error: {e}")
            self.update_status_label.configure(text=f"Error: {e}", text_color="red")
            self.app.after(5000, lambda: self.update_status_label.configure(text=""))

    def _handle_uninstall(self):
        """Handle the Uninstall button click with confirmation."""
        import tkinter.messagebox

        confirmed = tkinter.messagebox.askyesno(
            "Uninstall Resistine",
            "Are you sure you want to completely uninstall Resistine?\n\n"
            "This will remove all VPN configurations, application data, "
            "and the application itself.\n\n"
            "This action cannot be undone.",
        )
        if not confirmed:
            return

        self.uninstall_button.configure(state="disabled")
        self.uninstall_status_label.configure(text="Uninstalling...", text_color="orange")
        self.app.update_idletasks()

        try:
            from utils import uninstall

            def _progress(msg):
                self.uninstall_status_label.configure(text=msg)
                self.app.update_idletasks()

            success, message = uninstall.run_uninstall(self.app, progress_callback=_progress)

            if success:
                self.app.destroy()
            else:
                self.uninstall_button.configure(state="normal")
                self.uninstall_status_label.configure(text=message, text_color="red")
        except Exception as e:
            logger.error(f"Uninstall error: {e}")
            self.uninstall_button.configure(state="normal")
            self.uninstall_status_label.configure(text=f"Error: {e}", text_color="red")

    def _handle_logout(self):
        """Handle the Log Out button click with confirmation."""
        import tkinter.messagebox

        confirmed = tkinter.messagebox.askyesno(
            "Log Out",
            "Are you sure you want to log out?\n\n"
            "You will need to sign in again to use Resistine.",
        )
        if not confirmed:
            return

        # Disconnect VPN before clearing auth state
        try:
            import platform
            if platform.system() == "Windows":
                from plugins.vpn.wireguard.vpn_windows_client import disconnect
                disconnect("resistine_default")
            else:
                from plugins.vpn.wireguard.vpn_functions_darwin import stop_vpn
                stop_vpn()
        except Exception as e:
            logger.warning(f"VPN disconnect on logout failed: {e}")

        # Clear auth state
        settings.set("auth", "logged_in", False)

        # Remove saved email
        email_file_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
            "utils",
            "email-settings.txt",
        )
        if os.path.exists(email_file_path):
            try:
                os.remove(email_file_path)
            except Exception as e:
                logger.error(f"Failed to remove email settings: {e}")

        # Tear down dashboard and show login screen
        try:
            from plugins.login.main import Plugin as LoginPlugin

            for widget in self.app.winfo_children():
                widget.destroy()

            self.app.grid_rowconfigure(0, weight=1)
            self.app.grid_columnconfigure(0, weight=1)
            self.app.grid_columnconfigure(1, weight=0)

            login_plugin = LoginPlugin(self.app)
            login_plugin.show()
        except Exception as e:
            logger.error(f"Failed to show login screen: {e}")
            self.app.show_notification(f"Logout failed: {e}", type="error")

    def change_appearance_mode(self, new_appearance_mode: str):
        try:
            customtkinter.set_appearance_mode(new_appearance_mode)
        finally:
            self._apply_theme_refresh()
