## @file plugins/dashboard/main.py
## @package dashboard_plugin
## @namespace dashboard_plugin
## @class dashboard_plugin::Plugin

"""Dashboard plugin UI.

This implementation ports the UI_Dev dashboard layout ideas (protection panel + grid cards)
while preserving existing functionality (plugin list + navigation via App.select_frame_by_name).

IMPORTANT:
- UI only (no backend changes)
- Logo is in side menu only (not on dashboard)
- Does NOT use Resistine shield / RSheild assets

Author: P3, Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from plugins.plugin_manager import PluginManager


class Plugin(BasePlugin):
    """Dashboard plugin."""

    def __init__(self, app):
        super().__init__(
            id="001",
            version="2025.01.01",
            order=1,
            name="Dashboard",
            status=None,
            description="See your protection status at a glance.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Dashboard", "ES": "Panel", "FR": "Tableau de bord"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "home_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "home_dark.png"
            ),
            uninstall_enabled=False,
        )
        self.app = app
        self._dashboard_logo_image = None
        self.status = self.get_status()

    def _effective_appearance_mode(self) -> str:
        # Use user_interface's detection if available
        try:
            # Accessing the internal function if necessary, or just rely on ctk
            # But user_interface has `_effective_appearance_mode`.
            # Let's just use ctk for now or replicate logic.
            # Actually, user_interface exposed it? No, it's `def _effective_appearance_mode`.
            pass
        except Exception:
            pass
        mode = customtkinter.get_appearance_mode()
        return mode

    def create_main_screen(self):
        # Modern main frame with proper spacing
        self.main_frame = customtkinter.CTkFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=0)  # protection panel
        self.main_frame.grid_rowconfigure(1, weight=0)  # grid
        self.main_frame.grid_rowconfigure(2, weight=1)  # spacer to push content up

        appearance_mode = self._effective_appearance_mode()
        is_dark = appearance_mode == "Dark"

        # --- Protection panel (Sleek SOC-style) ---
        text_primary = ThemeManager.theme["CTkLabel"]["text_color"]
        accent_blue = ThemeManager.theme["CTkButton"]["border_color"]
        text_secondary = ThemeManager.theme["CTkLabel"]["text_color"]  # Fallback

        # Container for the protection panel to control its width and centering
        protection_container = customtkinter.CTkFrame(
            self.main_frame, fg_color="transparent"
        )
        protection_container.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 0))
        protection_container.grid_columnconfigure(0, weight=1)

        protection_panel = customtkinter.CTkFrame(
            protection_container,
            corner_radius=15,
            fg_color="transparent",
            border_width=0,
            width=600,  # Decreased width
        )
        protection_panel.grid(row=0, column=0, sticky="n")  # Center horizontally
        protection_panel.grid_columnconfigure(0, weight=1)
        protection_panel.grid_propagate(True)

        protection_label = customtkinter.CTkLabel(
            protection_panel,
            text="You are protected!",
            font=customtkinter.CTkFont(family="Inter", size=22, weight="bold"),
            text_color=accent_blue,
            justify="center",
        )
        protection_label.grid(row=0, column=0, sticky="ew", padx=40, pady=(15, 5))

        # --- Plugins grid ---
        if not hasattr(self.app, "plugin_list") or not self.app.plugin_list:
            plugin_list = PluginManager(self.app).plugins
        else:
            plugin_list = self.app.plugin_list

        # Filter plugins for the grid:
        # Exclude current plugin (Dashboard)
        # Exclude hidden plugins using order -1
        # Order 0 is allowed (e.g. Login)
        plugins = [
            p for p in plugin_list 
            if p.get_name() != "Dashboard" and p.order != -1
        ]
        
        rows, cols = self.app.calculate_rows_cols(len(plugins))

        content_frame = customtkinter.CTkFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        content_frame.grid(row=1, column=0, sticky="new", padx=15, pady=0)
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)

        self.grid_frame = self.app.create_grid(
            frame=content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
        )
        self.grid_frame.grid_columnconfigure(
            tuple(range(len(cols))), weight=1, uniform="cols"
        )
        self.grid_frame.grid_rowconfigure(tuple(range(len(rows))), weight=0)

        def open_plugin(p):
            # Preserve existing functionality: use app frame switching (updates sidebar state)
            try:
                self.app.select_frame_by_name(
                    f"frame_{p.get_name()}", button=p.get_button()
                )
            except Exception:
                p.create_main_screen().grid(row=0, column=1, sticky="nsew")

        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True,
                truncate=True
            )

        return self.main_frame
