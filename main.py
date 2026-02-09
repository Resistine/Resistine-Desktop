## @file main.py
## @namespace main
"""
This script is to run the main window for the Resistine AI EndPoint application.
Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import argparse
import os
import sys

import customtkinter
import customtkinter.windows.widgets.ctk_scrollable_frame as _sf

# Patch customtkinter bug where scroll events pass a string instead of a widget
_orig_check = _sf.CTkScrollableFrame.check_if_master_is_canvas
def _patched_check(self, widget):
    if isinstance(widget, str):
        return False
    return _orig_check(self, widget)
_sf.CTkScrollableFrame.check_if_master_is_canvas = _patched_check

# DEPRECATED: Debug Window - controlled by command-line arguments
from gui.debug_window import DebugWindow
from gui.inspector import RuntimeInspector
from gui.user_interface import AppUI
from utils import functions as functions
from utils import settings
from utils.logger import logger, setup_logging

DEBUG_WINDOW = False
DEBUG = False


def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for both dev and PyInstaller bundled app.
    
    When running from source, returns path relative to the script directory.
    When running from a PyInstaller bundle, returns path relative to the 
    temporary extraction directory (sys._MEIPASS).
    """
    if hasattr(sys, '_MEIPASS'):
        # Running in PyInstaller bundle
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # Running from source - use the script's directory
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


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
        customtkinter.set_default_color_theme(resource_path("resources/themes/resistine_ctk.json"))
        customtkinter.set_appearance_mode("System")

        if DEBUG_WINDOW:
            self.debug_window = DebugWindow(self)
            self.debug_window.create_debug_window()

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

        # Initialize auto-updater (cross-platform: Sparkle on macOS, stubs on Win/Linux)
        try:
            from utils import update_manager

            update_manager.init(self)
        except Exception as e:
            logger.warning(f"Failed to start auto-updater: {e}")

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        """Clean up resources before closing."""
        try:
            from utils import update_manager

            update_manager.shutdown()
        except Exception:
            pass
        self.destroy()


# class App


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

    app.mainloop()
