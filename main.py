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

from plugins.plugin_manager import PluginManager
from utils import functions as functions
from utils import settings

# Debug Window - controlled by command-line arguments
from utils.debug_window import DebugWindow
from utils.inspector import RuntimeInspector

DEBUG_WINDOW = False
DEBUG = False


class App(customtkinter.CTk):
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
        window_width = int(screen_width * 0.75)
        window_height = int(screen_height * 0.8)
        position_right = int(screen_width / 2 - window_width / 2)
        position_down = int(screen_height / 2 - window_height / 2)
        self.geometry(
            f"{window_width}x{window_height}+{position_right}+{position_down}"
        )

        # Check if already logged in
        if settings.get("auth", "logged_in", False):
            print("✅ User already logged in, skipping login screen...")
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

    def create_dashboard(self):
        """
        Create the main dashboard of the application, including loading plugins and creating navigation buttons.
        """

        for widget in self.winfo_children():
            if isinstance(widget, (tk.Toplevel, customtkinter.CTkToplevel)):
                continue
            widget.grid_forget()

        # 2. Re-configure the main window (self) for the 2-column dashboard layout
        self.grid_rowconfigure(0, weight=1)  # Only one row needed
        self.grid_columnconfigure(
            0, weight=0
        )  # Column 0 (Navigation): Weight 0 (only takes necessary width)
        self.grid_columnconfigure(1, weight=1)

        # Getting the plugin list from the PluginManager located in plugins folder.
        if not hasattr(App, "plugin_list"):
            App.plugin_list = PluginManager(self).plugins
        else:
            if len(App.plugin_list) < len(PluginManager(self).plugins):
                App.plugin_list = PluginManager(self).plugins
        self.plugin_list = App.plugin_list
        number_plugins = len(self.plugin_list) + 1

        self.navigation_frame = customtkinter.CTkFrame(self, corner_radius=0)
        self.navigation_frame.grid(row=0, column=0, sticky="nsew")
        self.navigation_frame.grid_rowconfigure(number_plugins, weight=1)

        self.navigation_frame_label = customtkinter.CTkLabel(
            self.navigation_frame,
            text="Resistine",
            image=None,
            compound="left",
            font=customtkinter.CTkFont(size=15, weight="bold"),
        )
        self.navigation_frame_label.grid(row=0, column=0, padx=20, pady=20)

        self.frames = {}
        row = 1
        for plugin in self.plugin_list:
            frame_name = f"frame_{plugin.get_name()}"
            self.frames[frame_name] = plugin

            try:
                # Create the buttons for each plugin
                plugin.set_button(
                    functions.create_tab_button(
                        self.navigation_frame,
                        plugin.get_name(),
                        plugin.get_icon(),
                        lambda p=plugin: self.select_frame_by_name(
                            f"frame_{p.get_name()}", button=p.get_button()
                        ),
                        row,
                        0,
                    )
                )
            except Exception as e:
                print(f"Error loading plugin button {plugin.get_name()}, Error: {e}")
            row += 1

        self.select_frame_by_name(
            "frame_Dashboard", button=self.frames["frame_Dashboard"].get_button()
        )

    def select_frame_by_name(self, name, button=None):
        """
        Select and display the specified frame, and update the button appearance.

        :param name: The name of the frame to display.
        :param button: The button associated with the frame.
        """
        for frame_name, frame in self.frames.items():
            if frame_name == name:
                if button:
                    button.configure(fg_color=("gray75", "gray25"))
                frame.create_main_screen().grid(row=0, column=1, sticky="nsew")
            else:
                if button:
                    button.configure(fg_color="transparent")
                frame.create_main_screen().grid_forget()


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
