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

Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter

from plugins.base_plugin import BasePlugin
from plugins.plugin_manager import PluginManager
from utils import functions as myfunctions


class Plugin(BasePlugin):
    """Dashboard plugin."""

    def __init__(self, app):
        super().__init__(
            id="001",
            order=1,
            name="Dashboard",
            status="OK",
            description="This plugin allows you to view the dashboard.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Dashboard", "ES": "Panel", "FR": "Tableau de bord"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "home_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "home_dark.png"
            ),
        )
        self.app = app
        self._dashboard_logo_image = None

    def _effective_appearance_mode(self) -> str:
        if hasattr(myfunctions, "_effective_appearance_mode"):
            try:
                return myfunctions._effective_appearance_mode()
            except Exception:
                pass
        mode = customtkinter.get_appearance_mode()
        return "Dark" if mode == "Dark" else "Light"

    def create_main_screen(self):
        # Modern main frame with proper spacing
        self.main_frame = customtkinter.CTkFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=0)  # protection panel
        self.main_frame.grid_rowconfigure(1, weight=1)  # grid
        
        appearance_mode = self._effective_appearance_mode()
        is_dark = appearance_mode == "Dark"

        resistine_blue = "#0D5394"
        panel_bg = "#1A1A1A" if is_dark else "#ffffff"
        text_color = "#ffffff" if is_dark else "#000000"

        
        
        # --- Protection panel (Sleek SOC-style) ---
        panel_bg = myfunctions.SOC_THEME["colors"]["card_bg"]
        text_primary = myfunctions.SOC_THEME["colors"]["text_primary"]
        accent_blue = myfunctions.SOC_THEME["colors"]["accent_blue"]

        # Container for the protection panel to control its width and centering
        protection_container = customtkinter.CTkFrame(self.main_frame, fg_color="transparent")
        protection_container.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 5))
        protection_container.grid_columnconfigure(0, weight=1)

        protection_panel = customtkinter.CTkFrame(
            protection_container,
            corner_radius=15,
            fg_color=panel_bg,
            border_width=1,
            border_color=myfunctions.SOC_THEME["colors"]["card_border"],
            width=600 # Decreased width
        )
        protection_panel.grid(row=0, column=0, sticky="n") # Center horizontally
        protection_panel.grid_columnconfigure(0, weight=1)
        protection_panel.grid_propagate(True)

        protection_label = customtkinter.CTkLabel(
            protection_panel,
            text="SYSTEM STATUS: PROTECTED",
            font=customtkinter.CTkFont(family="Inter", size=18, weight="bold"),
            text_color=accent_blue,
            justify="center"
        )
        protection_label.grid(row=0, column=0, sticky="ew", padx=40, pady=(15, 5))

        subtitle_label = customtkinter.CTkLabel(
            protection_panel,
            text="All security modules are actively monitoring for threats.",
            font=customtkinter.CTkFont(family="Inter", size=12, weight="normal"),
            text_color=myfunctions.SOC_THEME["colors"]["text_secondary"],
            justify="center"
        )
        subtitle_label.grid(row=1, column=0, sticky="ew", padx=40, pady=(0, 15))


        # --- Plugins grid ---
        if not hasattr(self.app, "plugin_list") or not self.app.plugin_list:
            plugin_list = PluginManager(self.app).plugins
        else:
            plugin_list = self.app.plugin_list

        plugins = plugin_list[1:]  # omit Dashboard itself
        rows, cols = myfunctions.calculate_rows_cols(len(plugins))

        content_frame = customtkinter.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        content_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(5, 15))
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)

        self.grid_frame = myfunctions.create_grid(
            frame=content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
        )
        self.grid_frame.grid_columnconfigure(tuple(range(len(cols))), weight=1, uniform="cols")
        self.grid_frame.grid_rowconfigure(tuple(range(len(rows))), weight=1, uniform="rows")

        def open_plugin(p):
            # Preserve existing functionality: use app frame switching (updates sidebar state)
            try:
                self.app.select_frame_by_name(f"frame_{p.get_name()}", button=p.get_button())
            except Exception:
                p.create_main_screen().grid(row=0, column=1, sticky="nsew")

        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            myfunctions.create_plugin_card(r, c, self.grid_frame, plugin)

        return self.main_frame
