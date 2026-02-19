# -*- coding: utf-8 -*-
# @file plugins/login/main.py
# @namespace plugins.login.main
# Description: Main window of the Resistine login plugin for Resistine Desktop Application

# Author: Sherwin and the Resistine Team
# Copyright: Resistine (c) 2025
# Licensed under the GNU General Public License v2 or later


# Removed unused json import
import os
import re
import sys

import customtkinter
from PIL import Image
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin

# Removed unused config import
from plugins.login.api import LoginAPI

# Removed unused settings import
from utils.logger import logger

# Removed standard logging setup


def _resource_path(relative_path: str) -> str:
    """Resolve path for both dev and PyInstaller bundles."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        relative_path,
    )


# Platform Specific Imports
import platform
if platform.system() == "Windows":
    from plugins.vpn.wireguard.vpn_functions_windows import setup_vpn_keys, save_vpn_configuration
elif platform.system() == "Linux":
    from plugins.vpn.wireguard.vpn_functions_linux import setup_vpn_keys, save_vpn_configuration
elif platform.system() == "Darwin":
    from plugins.vpn.wireguard.vpn_functions_darwin import setup_vpn_keys, save_vpn_configuration


class Plugin(BasePlugin):
    REGISTRATION_GRID_ROWS = 8
    REGISTRATION_GRID_COLS = 3

    def __init__(self, app):
        super().__init__(
            id="007",
            version="2025.01.01",
            order=0,
            name="Login",
            status=None,
            description="Login to the Resistine application.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Login", "ES": "Acceso", "FR": "Connexion"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "login_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "login_dark.png"
            ),
        )
        self.app = app
        self.email = None
        self.status = self.get_status()

        # API endpoint
        self.api_base_url = "https://validate.resistine.work"
        self.api = LoginAPI(self.api_base_url)

        # Reference to the currently active input field
        self.active_input_entry = None

    def show(self):
        """
        Create and show the login screen.
        """
        self.login_frame = self.create_main_screen()
        self.login_frame.grid(row=0, column=0, sticky="nsew")

        # Configure grid to ensure login screen takes full window
        self.app.grid_rowconfigure(0, weight=1)
        self.app.grid_columnconfigure(0, weight=1)

        # Ensure login screen is on top
        self.login_frame.lift()

    def destroy(self):
        """
        Destroy the login screen and clean up resources.
        """
        if hasattr(self, "login_frame"):
            self.login_frame.destroy()
            del self.login_frame

    def create_main_screen(self):
        """
        Create the login screen matching the provided mockup.
        """
        logger.debug("Login plugin: Creating modern main screen...")
        self.login_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color=self.app.cget("fg_color")
        )
        self.login_frame.grid(row=0, column=0, sticky="nsew")

        # Main centering grid
        self.login_frame.grid_rowconfigure(0, weight=1)
        self.login_frame.grid_rowconfigure(1, weight=0)
        self.login_frame.grid_rowconfigure(2, weight=1)
        self.login_frame.grid_columnconfigure(0, weight=1)

        # Content container
        self.content_frame = customtkinter.CTkFrame(
            self.login_frame, corner_radius=0, fg_color="transparent"
        )
        self.content_frame.grid(row=1, column=0, sticky="n")
        self.content_frame.grid_columnconfigure(0, weight=1)

        # 1. Shield Logo
        shield_path = _resource_path("ResistineSheild.png")
        try:
            shield_img = Image.open(shield_path)
            shield_ctk = customtkinter.CTkImage(shield_img, size=(250, 250))
            self.shield_label = customtkinter.CTkLabel(
                self.content_frame, text="", image=shield_ctk
            )
            self.shield_label.grid(row=0, column=0, pady=(0, 30))
        except OSError as e:
            logger.warning(f"Shield logo load failed: {e}")

        # 2. Main Title
        self.title_label = customtkinter.CTkLabel(
            self.content_frame,
            text="Sign in with your Resistine account to get started.",
            font=customtkinter.CTkFont(family="Inter", size=16),
            text_color=("#333333", "#FFFFFF"),
        )
        self.title_label.grid(row=1, column=0, pady=(0, 25))

        # Get theme corner radius
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 15)

        # 3. Email Entry
        self.email_entry = customtkinter.CTkEntry(
            self.content_frame,
            placeholder_text="Enter your email address",
            width=400,
            height=45,
            corner_radius=corner_radius,
            border_width=1,
            font=customtkinter.CTkFont(family="Inter", size=14),
        )
        self.email_entry.grid(row=2, column=0, pady=(0, 20))
        self.active_input_entry = self.email_entry

        # 4. Sign in Button
        self.signin_button = customtkinter.CTkButton(
            self.content_frame,
            text="Sign in",
            command=self.handle_signin_click,
            width=400,
            height=45,
            corner_radius=corner_radius,
            fg_color="#0D5394",  # Professional blue
            hover_color="#0A4275",
            font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"),
        )
        self.signin_button.grid(row=3, column=0, pady=(0, 20))

        # 5. Create new account link
        self.create_account_btn = customtkinter.CTkButton(
            self.content_frame,
            text="Create new account",
            fg_color="transparent",
            hover_color=None,
            text_color=("#0D5394", "#3a7ebf"),
            font=customtkinter.CTkFont(family="Inter", size=15, weight="bold"),
            command=lambda: __import__("webbrowser").open(
                "https://resistine-main2-api2-27753069.dev.odoo.com/web/signup?redirect=%2Fodoo%3F"
            ),
        )
        self.create_account_btn.grid(row=4, column=0, pady=(0, 40))

        # 6. Status/Error Label (Hidden by default)
        self.status_label = customtkinter.CTkLabel(
            self.content_frame,
            text="",
            font=customtkinter.CTkFont(family="Inter", size=12),
            text_color="red",
        )
        self.status_label.grid(row=5, column=0)

        # 7. Footer
        footer_frame = customtkinter.CTkFrame(self.login_frame, fg_color="transparent")
        footer_frame.grid(row=2, column=0, sticky="s", pady=20)

        self.privacy_label = customtkinter.CTkLabel(
            footer_frame,
            text="Privacy and Cookies",
            font=customtkinter.CTkFont(family="Inter", size=12),
            text_color=("#0D5394", "#3a7ebf"),
            cursor="hand2",
        )
        self.privacy_label.pack(side="top")

        self.terms_label = customtkinter.CTkLabel(
            footer_frame,
            text="By signing in you agree to the Terms of Use",
            font=customtkinter.CTkFont(family="Inter", size=12),
            text_color=("#666666", "#AAAAAA"),
        )
        self.terms_label.pack(side="top", pady=(5, 0))

        # 8. Skip Button (Bottom Right)
        self.skip_button = customtkinter.CTkButton(
            self.login_frame,
            text="Skip",
            command=self.skip_login,
            width=80,
            height=30,
            corner_radius=corner_radius,
            fg_color="transparent",
            border_width=1,
            border_color=("#CCCCCC", "#444444"),
            text_color=("#666666", "#AAAAAA"),
            font=customtkinter.CTkFont(family="Inter", size=12),
        )
        self.skip_button.place(relx=0.98, rely=0.98, anchor="se")

        return self.login_frame

    def skip_login(self):
        """Skip login and go to dashboard."""
        logger.info("User skipped login")
        if hasattr(self, "login_frame"):
            self.login_frame.destroy()

        self.app.show_notification("Login skipped - some features may be unavailable", type="warning")
        self.app.create_dashboard()

    def handle_signin_click(self):
        """Handle the sign-in button click."""
        email = self.email_entry.get().strip()
        email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

        if not email:
            self.update_status("Please enter an email address", "red")
            return
        elif not re.match(email_regex, email):
            self.update_status("Please enter a valid email address", "red")
            return

        self.email = email
        self.send_otp_api(email)

    def transform_to_otp_input(self):
        """Transform the existing screen to show OTP entry."""
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 15)
        # Hide email entry and sign-in button
        if hasattr(self, "email_entry") and self.email_entry.winfo_exists():
            self.email_entry.destroy()
        if hasattr(self, "signin_button") and self.signin_button.winfo_exists():
            self.signin_button.destroy()
        if (
            hasattr(self, "create_account_btn")
            and self.create_account_btn.winfo_exists()
        ):
            self.create_account_btn.destroy()

        # Update title
        self.title_label.configure(text=f"Enter the 6-digit code sent to {self.email}")

        # Create OTP entry in same spot
        self.otp_entry = customtkinter.CTkEntry(
            self.content_frame,
            placeholder_text="Enter OTP",
            width=400,
            height=45,
            corner_radius=corner_radius,
            show="*",
            font=customtkinter.CTkFont(family="Inter", size=14),
        )
        self.otp_entry.grid(row=2, column=0, pady=(0, 20))
        self.active_input_entry = self.otp_entry
        self.otp_entry.bind("<KeyPress>", self.on_otp_key_press)
        self.otp_entry.focus_set()

        # Create Verify button
        self.verify_button = customtkinter.CTkButton(
            self.content_frame,
            text="Verify OTP",
            command=self.verify_otp,
            width=400,
            height=45,
            corner_radius=corner_radius,
            fg_color="#0D5394",
            font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"),
        )
        self.verify_button.grid(row=3, column=0, pady=(0, 20))

        # Back button to return to email entry
        self.back_button = customtkinter.CTkButton(
            self.content_frame,
            text="Back",
            fg_color="transparent",
            hover_color=None,
            text_color=("#0D5394", "#3a7ebf"),
            font=customtkinter.CTkFont(family="Inter", size=15, weight="bold"),
            command=self.back_to_email,
        )
        self.back_button.grid(row=4, column=0, pady=(0, 20))

    def back_to_email(self):
        """Navigate back from OTP screen to email entry screen."""
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 15)
        # Destroy OTP widgets
        if hasattr(self, "otp_entry") and self.otp_entry.winfo_exists():
            self.otp_entry.destroy()
        if hasattr(self, "verify_button") and self.verify_button.winfo_exists():
            self.verify_button.destroy()
        if hasattr(self, "back_button") and self.back_button.winfo_exists():
            self.back_button.destroy()

        # Restore title
        self.title_label.configure(
            text="Sign in with your Resistine account to get started."
        )

        # Recreate email entry
        self.email_entry = customtkinter.CTkEntry(
            self.content_frame,
            placeholder_text="Enter your email address",
            width=400,
            height=45,
            corner_radius=corner_radius,
            border_width=1,
            font=customtkinter.CTkFont(family="Inter", size=14),
        )
        self.email_entry.grid(row=2, column=0, pady=(0, 20))
        self.active_input_entry = self.email_entry
        self.email_entry.focus_set()

        # Recreate sign-in button
        self.signin_button = customtkinter.CTkButton(
            self.content_frame,
            text="Sign in",
            command=self.handle_signin_click,
            width=400,
            height=45,
            corner_radius=corner_radius,
            fg_color="#0D5394",
            hover_color="#0A4275",
            font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"),
        )
        self.signin_button.grid(row=3, column=0, pady=(0, 20))

        # Recreate account link
        self.create_account_btn = customtkinter.CTkButton(
            self.content_frame,
            text="Create new account",
            fg_color="transparent",
            hover_color=None,
            text_color=("#0D5394", "#3a7ebf"),
            font=customtkinter.CTkFont(family="Inter", size=15, weight="bold"),
            command=lambda: __import__("webbrowser").open(
                "https://resistine-main2-api2-27753069.dev.odoo.com/web/signup?redirect=%2Fodoo%3F"
            ),
        )
        self.create_account_btn.grid(row=4, column=0, pady=(0, 40))

        # Clear status
        self.update_status("", "white")

    def update_status(self, message, color="white"):
        """Update status label with message and color"""
        if hasattr(self, "status_label") and self.status_label.winfo_exists():
            self.status_label.configure(text=message, text_color=color)
            self.status_label.update()

    def get_name(self):
        return "Login"

    def get_icon(self):
        return None

    def get_button(self):
        return getattr(self, "button", None)

    def set_button(self, button):
        self.button = button

    def send_otp_api(self, email):
        """Send OTP via API."""
        success, message, _ = self.api.send_otp(email)
        if success:
            self.app.show_notification(message, type="info")
            self.transform_to_otp_input()
        else:
            self.update_status(message, "red")
            self.app.show_notification(message, type="error")

    def verify_otp(self):
        """Verify OTP via API."""
        otp = self.otp_entry.get().strip()
        if not otp:
            self.update_status("Please enter OTP", "red")
            return

        # Phase 1: Generate VPN keys (never raises — returns None on failure)
        public_key = setup_vpn_keys()
        if not public_key:
            msg = "Failed to generate encryption keys"
            self.update_status(msg, "red")
            self.app.show_notification(msg, type="error")
            return

        # Phase 2: Verify OTP via API (never raises — returns tuple)
        success, message, result = self.api.verify_otp(
            email=self.email,
            otp=otp,
            public_key=public_key,
            host_url="rfr1.resisti.net",  # TODO: Move to config
            vpn_name="testVPNapi"         # TODO: Move to config
        )

        if not success:
            logger.error(f"Login failed: {message}")
            self.update_status(message, "red")
            self.app.show_notification(message, type="error")
            return

        # Phase 3: Post-login processing (API succeeded)
        logger.info("Login successful")
        self.app.show_notification("Login successful!", type="info")

        # Persist the authenticated email for other plugins (Settings, Wazuh, etc.)
        from utils import settings as app_settings
        app_settings.set("auth", "email", self.email)

        # Save VPN config if provided (never raises — returns None on failure)
        config_data = result.get("vpn_config") or result.get("data")
        if config_data:
            config_path = save_vpn_configuration(config_data, config_name="resistine_default")
            if config_path:
                from plugins.vpn.config_manager import VPNConfigManager, RESISTINE_CONFIG_NAME
                mgr = VPNConfigManager(os.path.dirname(config_path))
                mgr.register_config(RESISTINE_CONFIG_NAME, source="api")
                mgr.set_active_config(RESISTINE_CONFIG_NAME)
            else:
                logger.warning("VPN config from API could not be saved")
        else:
            logger.warning("No VPN config in API response (keys: %s)", list(result.keys()))

        # Phase 4: Transition to next screen
        from utils import settings as app_settings
        needs_onboarding = (
            platform.system() == "Darwin"
            and not app_settings.get("vpn", "onboarding_complete", False)
        )

        if needs_onboarding:
            self._transition_to_onboarding()
        else:
            app_settings.set("auth", "logged_in", True)
            self.destroy()
            self.app.create_dashboard()

    def _transition_to_onboarding(self):
        """Transition from login to VPN onboarding.

        Constructs the onboarding screen BEFORE destroying the login frame,
        so if construction fails the login screen stays visible.
        """
        from plugins.login.vpn_onboarding import VPNOnboardingScreen

        def on_onboarding_complete():
            self.app.create_dashboard()
            self.app.after(100, lambda: self.app.select_frame_by_name("frame_VPN"))

        # Build onboarding first, then tear down login
        self._onboarding = VPNOnboardingScreen(self.app, on_onboarding_complete)
        self.destroy()
        self._onboarding.show()

    def on_otp_key_press(self, event):
        """Handle key press in OTP entry."""
        if event.keysym == "Return":
            self.verify_otp()
