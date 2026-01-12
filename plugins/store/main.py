# @file plugins/store/main.py
""" "
Store plugin for the Resistine application.
This plugin allows users to download and install new plugins from the store.
Author: Peres J., P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import webbrowser

import customtkinter
from PIL import Image

from plugins.base_plugin import BasePlugin
from plugins.plugin_manager import PluginManager

# DNS Configuration - Change this value to update DNS across the application
DNS_SERVER = "10.49.11.10"


class Plugin(BasePlugin):
    """
    @brief Plugin class for the Store plugin.
    Plugin class for the Store plugin, that allows user install new plugins from the store.
    """

    def __init__(self, app):
        """
        @brief Initialize the Store plugin.
        Initialize the Store plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="004",
            version="2025.01.01",
            order=100,
            name="Store",
            status=None,
            description="This plugin allows you to download and install new plugins.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Store", "ES": "Tienda", "FR": "Magasin"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "store_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "store_dark.png"
            ),
            uninstall_enabled=False,
        )
        self.app = app
        self.status = self.get_status()

    def create_main_screen(self):
        """
        @brief Create the main screen for the Store plugin.
        """
        self.main_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=10)

        # Title frame
        self.title_frame = customtkinter.CTkFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        self.title_frame.grid(row=0, column=0, sticky="nsew")
        self.title_frame.grid_columnconfigure(0, weight=1)

        self.title_label = customtkinter.CTkLabel(
            self.title_frame,
            text="Store",
            font=customtkinter.CTkFont(size=30, weight="bold"),
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # --- Plugins grid ---
        manager = self.app.get_plugin_manager()
        installed_plugins = manager.plugins
        available_remote = manager.get_available_plugins()
        
        # Wrap remote plugins that aren't installed yet
        installed_ids = {p.id for p in installed_plugins}
        
        plugins = list(installed_plugins)
        for rp in available_remote:
            if rp["id"] not in installed_ids:
                plugins.append(RemotePluginWrapper(self.app, rp))
        
        # Sort by name for the store
        plugins = sorted(plugins, key=lambda x: x.get_name())
        
        rows, cols = self.app.calculate_rows_cols(len(plugins))

        content_frame = customtkinter.CTkScrollableFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        content_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=0)
        content_frame.grid_columnconfigure(0, weight=1)

        self.grid_frame = self.app.create_grid(
            frame=content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
        )
        
        # Helper for extra buttons
        def inject_store_buttons(container, p):
            # Info Button
            info_btn = customtkinter.CTkButton(
                container,
                text="Info",
                height=26,
                width=80,
                command=lambda p=p: self.app.show_readme(p) if not isinstance(p, RemotePluginWrapper) else self.show_remote_info(p),
                fg_color=("#3B8ED0", "#1F6AA5"),
                hover_color=("#367EBB", "#144870"),
                font=customtkinter.CTkFont(size=12)
            )
            info_btn.grid(row=0, column=0, padx=5, pady=5)

            if isinstance(p, RemotePluginWrapper):
                # Install Button
                install_btn = customtkinter.CTkButton(
                    container,
                    text="Install",
                    height=26,
                    width=80,
                    command=lambda p=p: self.handle_install(p),
                    fg_color=("#2ECC71", "#27AE60"),
                    hover_color=("#27AE60", "#219150"),
                    font=customtkinter.CTkFont(size=12)
                )
                install_btn.grid(row=0, column=1, padx=5, pady=5)
            else:
                # Uninstall Button (if enabled)
                if getattr(p, "uninstall_enabled", True):
                    uninstall_btn = customtkinter.CTkButton(
                        container,
                        text="Uninstall",
                        height=26,
                        width=80,
                        command=lambda p=p: self.handle_uninstall(p),
                        fg_color="transparent",
                        text_color="#FF4444",
                        hover_color=("#ffebee", "#2b1b1b"),
                        font=customtkinter.CTkFont(size=12)
                    )
                    uninstall_btn.grid(row=0, column=1, padx=5, pady=5)

        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True, 
                extra_buttons_func=inject_store_buttons
            )

        return self.main_frame

    def handle_install(self, remote_plugin):
        """Handle plugin installation."""
        from utils.logger import logger
        logger.info(f"Store: Initiating installation for {remote_plugin.get_name()} ({remote_plugin.id})")
        
        success, message = self.app.get_plugin_manager().download_plugin(remote_plugin.url, remote_plugin.id, remote_plugin.get_name())
        logger.info(f"Store: Installation result for {remote_plugin.get_name()}: success={success}, msg={message}")
        
        if success:
            self.app.show_notification(message, type="info")
            # Refresh screen
            self.app.select_frame_by_name("frame_Store")
        else:
            self.app.show_notification(message, type="error")

    def show_remote_info(self, remote_plugin):
        """Show info for a remote plugin."""
        import tkinter.messagebox
        tkinter.messagebox.showinfo(remote_plugin.get_name(), remote_plugin.get_description())

    def handle_uninstall(self, plugin):
        """Handle plugin uninstallation with confirmation."""
        import tkinter.messagebox
        if tkinter.messagebox.askyesno("Uninstall Plugin", f"Are you sure you want to uninstall {plugin.get_name()}?"):
             success, res = self.app.get_plugin_manager().uninstall_plugin(plugin)
             if success:
                 self.app.show_notification(res, type="info")
                 # Refresh screen
                 self.app.select_frame_by_name("frame_Store")
             else:
                 self.app.show_notification(res, type="error")

class RemotePluginWrapper:
    """Wrapper to make remote plugin dicts compatible with AppUI.create_plugin_card."""
    def __init__(self, app, data):
        self.app = app
        self.id = data["id"]
        self.name = data["name"]
        self.description = data["description"]
        self.url = data["url"]
        self.order = data.get("order", 99)
        self.status = "Available"
        
    def get_name(self): return self.name
    def get_description(self): return self.description
    def get_status(self): return self.status

    def get_icon(self):
        # Return default store icon for remote plugins since we can't reliably load remote icons yet
        # Note: icon_light.png contains dark icon (for light backgrounds)
        #       icon_dark.png contains light/white icon (for dark backgrounds)
        # So we need to swap them for CTkImage (same as base_plugin.py does)
        icons_path = os.path.dirname(os.path.realpath(__file__))
        light_image = Image.open(os.path.join(icons_path, "store_light.png"))
        dark_image = Image.open(os.path.join(icons_path, "store_dark.png"))
        return customtkinter.CTkImage(
            light_image=dark_image,  # Use dark icon (white) for light mode
            dark_image=light_image,  # Use light icon (dark) for dark mode
            size=(50, 50)
        )
