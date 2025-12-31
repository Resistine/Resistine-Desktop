## @file main.py
## @namespace main
"""
This script is to run the main window for the Resistine AI EndPoint application.
Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import argparse
import logging
import os
import sys
import tkinter as tk

import customtkinter
from PIL import Image

from plugins.plugin_manager import PluginManager
from utils import functions as functions
from utils import settings
from utils import user_interface as user_interface

# Debug Window - controlled by command-line arguments
from utils.debug_window import DebugWindow
from utils.inspector import RuntimeInspector

DEBUG_WINDOW = False
DEBUG = False


class App(user_interface.AppUI):
    """
    @brief Main application class for Resistine.
    Main application class for Resistine.
    """

    def __init__(self):
        """
        @brief Initialize the main application window.
        Initialize the main application window, set its title, size, and position.
        Check if the email is registered and create the appropriate screen.
        """
        super().__init__()

        # Theme: fixed Resistine CTk theme; only appearance mode varies (System/Light/Dark)
        customtkinter.set_default_color_theme("resources/themes/resistine_ctk.json")
        customtkinter.set_appearance_mode("System")

        if DEBUG_WINDOW:
            self.debug_window = DebugWindow(self)
            self.debug_window.create_debug_window()

        # Things to run when app is launched
        if sys.platform == "darwin":
            # Register privileged helper on macOS (only runs once per install)
            from plugins.vpn.wireguard.vpn_functions_darwin import (
                ensure_helper_registered,
            )

            ensure_helper_registered()

        self.title("Resistine")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = int(screen_width * 0.7)
        window_height = int(screen_height * 0.7)
        position_right = int(screen_width / 2 - window_width / 2)
        position_down = int(screen_height / 2 - window_height / 2)
        self.geometry(
            f"{window_width}x{window_height}+{position_right}+{position_down}"
        )

        # Check if already logged in
        if settings.get("auth", "logged_in", False):
            print("✅ User already logged in.")
            self.create_dashboard()
        else:
            # Always show login screen since we're using Odoo authentication
            print("🔐 Creating login screen...")
            from plugins.login.main import Plugin as LoginPlugin

            login_plugin = LoginPlugin(self)
            login_plugin.show()
            print("✅ Login screen created")

        # Ensure the window is visible
        self.update()


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Resistine Desktop Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode for real-time debugging",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging based on configuration and flags
    log_level = getattr(logging, args.log_level)

    # Determine if we should be in DEBUG mode
    if args.debug or functions.is_running_in_ide():
        DEBUG = True

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # DEPRECATED: Debug window flag can be set from code only
    if DEBUG_WINDOW:
        logging.info("Debug window enabled")

    # Start the application
    app = App()

    if DEBUG:
        logging.info("Debug mode enabled")
        logging.info("Platform: %s", sys.platform)
        logging.info("Python version: %s", sys.version)
        logging.info("Working directory: %s", os.getcwd())
        logging.info("Running in IDE: %s", functions.is_running_in_ide())

        # Attach Inspector
        app.inspector = RuntimeInspector(app)

    app.mainloop()
