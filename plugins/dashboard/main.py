## @file plugins/dashboard/main.py
## @package dashboard_plugin
## @namespace dashboard_plugin
## @class dashboard_plugin::Plugin

"""Dashboard plugin UI.

This implementation ports the UI_Dev dashboard layout ideas (protection panel + grid cards)
while preserving existing functionality (plugin list + navigation via App.select_frame_by_name).

IMPORTANT:
- UI only (no backend changes)
- Includes Resistine logo top-left
- Does NOT use Resistine shield / RSheild assets

Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

import customtkinter
from PIL import Image

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
        self.main_frame.grid_rowconfigure(0, weight=0)  # header
        self.main_frame.grid_rowconfigure(1, weight=0)  # protection panel
        self.main_frame.grid_rowconfigure(2, weight=1)  # grid

        appearance_mode = self._effective_appearance_mode()
        is_dark = appearance_mode == "Dark"

        resistine_blue = "#0D5394"
        panel_bg = "#1A1A1A" if is_dark else "#ffffff"
        text_color = "#ffffff" if is_dark else "#000000"

        # --- Header (logo top-left) ---
        header = customtkinter.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        header.grid_columnconfigure(0, weight=0)
        header.grid_columnconfigure(1, weight=1)

        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
            "ResistineLogoWhiteText.png",
        )
        self._dashboard_logo_image = None
        if os.path.exists(logo_path):
            try:
                logo_img = Image.open(logo_path)
                max_width = 160
                aspect_ratio = logo_img.height / logo_img.width if logo_img.width else 1
                logo_height = int(max_width * aspect_ratio)
                logo_img = logo_img.resize((max_width, logo_height), Image.Resampling.LANCZOS)
                self._dashboard_logo_image = customtkinter.CTkImage(
                    light_image=logo_img,
                    dark_image=logo_img,
                    size=(max_width, logo_height),
                )
            except Exception as e:
                print(f"Dashboard: failed to load logo: {e}")
                self._dashboard_logo_image = None

        if self._dashboard_logo_image:
            logo_label = customtkinter.CTkLabel(header, text="", image=self._dashboard_logo_image)
        else:
            logo_label = customtkinter.CTkLabel(
                header,
                text="Resistine",
                font=customtkinter.CTkFont(size=20, weight="bold"),
                text_color=text_color,
            )
        logo_label.grid(row=0, column=0, sticky="w")

        # --- Protection panel (UI_Dev-inspired, but no shield image) ---
        protection_panel = customtkinter.CTkFrame(
            self.main_frame,
            corner_radius=20,
            fg_color=panel_bg,
            border_width=2,
            border_color=resistine_blue,
        )
        protection_panel.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 15))
        protection_panel.grid_columnconfigure(0, weight=1)

        protection_label = customtkinter.CTkLabel(
            protection_panel,
            text="You are protected!",
            font=customtkinter.CTkFont(size=25, weight="bold"),
            text_color=text_color,
        )
        protection_label.grid(row=0, column=0, sticky="w", padx=20, pady=(18, 6))

        subtitle_label = customtkinter.CTkLabel(
            protection_panel,
            text="Resistine will alert you of any threats",
            font=customtkinter.CTkFont(size=16, weight="normal"),
            text_color=text_color,
        )
        subtitle_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 18))

        # --- Plugins grid ---
        if not hasattr(self.app, "plugin_list") or not self.app.plugin_list:
            plugin_list = PluginManager(self.app).plugins
        else:
            plugin_list = self.app.plugin_list

        plugins = plugin_list[1:]  # omit Dashboard itself
        rows, cols = myfunctions.calculate_rows_cols(len(plugins))

        content_frame = customtkinter.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        content_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=(0, 15))
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

            card = customtkinter.CTkFrame(
                self.grid_frame,
                corner_radius=20,
                fg_color=panel_bg,
                border_width=0,
                border_color=resistine_blue,
            )
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            card.grid_columnconfigure(0, weight=1)

            def _on_enter(_e, frame=card):
                frame.configure(border_width=2, border_color=resistine_blue)

            def _on_leave(_e, frame=card):
                frame.configure(border_width=0)

            card.bind("<Enter>", _on_enter)
            card.bind("<Leave>", _on_leave)

            # Icon (high-quality if plugin supports create_icon)
            icon_img = None
            try:
                if hasattr(plugin, "create_icon"):
                    icon_img = plugin.create_icon(size=(64, 64))
                else:
                    icon_img = plugin.get_icon()
            except Exception:
                icon_img = plugin.get_icon()

            icon_label = customtkinter.CTkLabel(card, text="", image=icon_img)
            icon_label.grid(row=0, column=0, pady=(14, 8))

            title_label = customtkinter.CTkLabel(
                card,
                text=plugin.get_name(),
                font=customtkinter.CTkFont(size=13, weight="bold"),
                text_color=text_color,
            )
            title_label.grid(row=1, column=0, pady=(0, 6))

            status_label = customtkinter.CTkLabel(
                card,
                text=str(plugin.get_status()),
                font=customtkinter.CTkFont(size=11),
                text_color=text_color,
            )
            status_label.grid(row=2, column=0, pady=(0, 14))

            for w in (card, icon_label, title_label, status_label):
                w.bind("<Button-1>", lambda _e, p=plugin: open_plugin(p))

        return self.main_frame
