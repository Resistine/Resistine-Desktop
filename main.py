## @file main.py
## @namespace main
"""
This script is to run the main window for the Resistine AI EndPoint application.
Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import argparse
import ctypes
import os
import sys

import customtkinter

# DEPRECATED: Debug Window - controlled by command-line arguments
from gui.debug_window import DebugWindow
from gui.inspector import RuntimeInspector
from gui.user_interface import AppUI
from utils import functions as functions
from utils import settings
from utils.logger import logger, setup_logging

DEBUG_WINDOW = False
DEBUG = False


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin():
    """
    Relaunch the current script with admin privileges (Windows only).
    """
    params = " ".join([f'"{arg}"' for arg in sys.argv])

    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",  # Triggers UAC
        sys.executable,  # python.exe or your packaged exe
        params,
        os.getcwd(),
        1,  # SW_SHOWNORMAL
    )


def was_relaunched():
    return "--elevated" in sys.argv


def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and PyInstaller
    """
    try:
        # PyInstaller temp folder
        base_path = sys._MEIPASS
    except AttributeError:
        # Normal execution
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class App(AppUI):
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
            logger.info("✅ User already logged in.")
            self.create_dashboard()
        else:
            # Always show login screen since we're using Odoo authentication
            logger.info("🔐 Creating login screen...")
            try:
                from plugins.login.main import Plugin as LoginPlugin

                login_plugin = LoginPlugin(self)
                login_plugin.show()
                logger.info("✅ Login screen created")
            except (ImportError, ModuleNotFoundError):
                logger.warning("⚠️ Login plugin not found. Skipping login screen.")
                self.create_dashboard()
            except Exception as e:
                logger.error(f"❌ Failed to load login plugin: {e}")
                self.create_dashboard()

        # Ensure the window is visible
        self.update()


# class App


if __name__ == "__main__":

    # CHECK: Why is this here?
    # Check for admin privileges on Windows
    if sys.platform == "win32" and not is_admin() and not was_relaunched():
        relaunch_as_admin()
        sys.exit(0)

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

    # Determine if we should be in DEBUG mode
    if args.debug or functions.is_running_in_ide():
        DEBUG = True

    # Configure logging based on configuration and flags
    setup_logging(level=args.log_level)

    # DEPRECATED: Debug window flag can be set from code only
    if DEBUG_WINDOW:
        logger.info("Debug window enabled")

    # Start the application
    app = App()

    if DEBUG:
        logger.info("Debug mode enabled")
        logger.info(f"Platform: {sys.platform}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {os.getcwd()}")
        logger.info(f"Running in IDE: {functions.is_running_in_ide()}")

        # Attach Inspector
        app.inspector = RuntimeInspector(app)

    # Application loop - run!
    app.mainloop()
