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
        # Use a ScrollableFrame for the dashboard to prevent clipping on smaller screens
        self.main_frame = customtkinter.CTkScrollableFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # We don't need fixed row weights in a scrollable frame as much, 
        # but we'll ensure the grid is clean.
        
        appearance_mode = self._effective_appearance_mode()
        is_dark = appearance_mode == "Dark"

        # --- Protection panel (Sleek SOC-style) ---
        accent_blue = ThemeManager.theme["CTkButton"]["border_color"]

        # Add a top spacer to move content down and away from the window title bar/header
        top_margin_spacer = customtkinter.CTkLabel(self.main_frame, text="", height=30)
        top_margin_spacer.grid(row=0, column=0, sticky="ew")

        # Simplified protection panel - directly in main_frame
        protection_label = customtkinter.CTkLabel(
            self.main_frame,
            text="You are protected!",
            font=customtkinter.CTkFont(family="Inter", size=26, weight="bold"),
            text_color=accent_blue,
            height=80, # Explicit height to prevent text clipping
            justify="center",
            anchor="center",
        )
        # Place at row 1 (below spacer)
        protection_label.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))

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
        
        # Store plugins for responsive rebuild
        self._dashboard_plugins = plugins
        
        # Responsive layout: determine max columns based on window width
        screen_width = self.app.winfo_screenwidth()
        window_width = self.app.winfo_width()
        if window_width <= screen_width * 0.6:
            max_cols = 2
            min_cols = None
        elif window_width >= screen_width * 0.9:
            max_cols = None
            min_cols = 4
        else:
            max_cols = None
            min_cols = None
        rows, cols = self.app.calculate_rows_cols(len(plugins), max_cols=max_cols, min_cols=min_cols)
        
        # Store current column count to detect changes
        self._current_cols = len(cols)
        self._current_max_cols = max_cols

        content_frame = customtkinter.CTkFrame(
            self.main_frame, corner_radius=0, fg_color="transparent"
        )
        # Place grid at row 2
        content_frame.grid(row=2, column=0, sticky="new", padx=15, pady=0)
        content_frame.grid_columnconfigure(0, weight=1)
        
        # Store reference for rebuilding
        self._content_frame = content_frame

        self.grid_frame = self.app.create_grid(
            frame=content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
            max_cols=max_cols,
            min_cols=min_cols,
        )

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
        
        # Bind resize handler to app window for responsive layout
        self._bind_responsive_resize()

        return self.main_frame
    
    def _bind_responsive_resize(self):
        """
        Bind a resize handler to rebuild grid when crossing 60% threshold.
        
        Uses a feature called debounce that limits the frequency of rebuilds during resizing.
        30ms debounce delay is used to ensure responsiveness without excessive rebuilds.
        """
        def on_resize(event=None):
            if not hasattr(self, '_dashboard_plugins') or not hasattr(self, '_content_frame'):
                return
            try:
                if not self._content_frame.winfo_exists():
                    return
            except:
                return
                
            screen_width = self.app.winfo_screenwidth()
            window_width = self.app.winfo_width()
            
            # Determine target columns based on width thresholds
            if window_width <= screen_width * 0.6:
                max_cols = 2
                min_cols = None
            elif window_width >= screen_width * 0.9:
                max_cols = None
                min_cols = 4
            else:
                max_cols = None
                min_cols = None
            
            # Calculate target columns
            target_cols = len(self.app.calculate_rows_cols(len(self._dashboard_plugins), max_cols=max_cols, min_cols=min_cols)[1])
            
            # Only rebuild if column count changed
            current = getattr(self, '_current_cols', None)
            if current == target_cols:
                return
            
            self._rebuild_grid(max_cols, min_cols)
        
        # Debounce: trigger quickly but avoid excessive rebuilds
        self._resize_after_id = None
        self._last_threshold_state = None
        self._cached_screen_width = self.app.winfo_screenwidth()  # Cache screen width
        
        def debounced_resize(event=None):
            # Skip if dashboard is not visible
            if not hasattr(self, 'main_frame') or not self.main_frame.winfo_ismapped():
                return
            
            # Quick check if we crossed the threshold (no debounce for threshold crossing)
            screen_width = self._cached_screen_width
            window_width = self.app.winfo_width()
            # Track state: 0=narrow (<=60%), 1=normal, 2=wide (>=90%)
            if window_width <= screen_width * 0.6:
                threshold_state = 0
            elif window_width >= screen_width * 0.9:
                threshold_state = 2
            else:
                threshold_state = 1
            
            # If threshold state changed, trigger immediately
            if self._last_threshold_state is not None and self._last_threshold_state != threshold_state:
                self._last_threshold_state = threshold_state
                if self._resize_after_id:
                    self.app.after_cancel(self._resize_after_id)
                    self._resize_after_id = None
                on_resize()
                return
            
            self._last_threshold_state = threshold_state
            
            # For other resizes, use debounce to avoid excessive rebuilds
            if self._resize_after_id:
                self.app.after_cancel(self._resize_after_id)
            self._resize_after_id = self.app.after(100, on_resize)
        
        self.app.bind("<Configure>", debounced_resize, add="+")
    
    def _rebuild_grid(self, max_cols, min_cols=None):
        """Rebuild the plugin grid with new column count."""
        if not hasattr(self, '_dashboard_plugins') or not hasattr(self, '_content_frame'):
            return
        
        plugins = self._dashboard_plugins
        
        # Destroy old grid
        if hasattr(self, 'grid_frame') and self.grid_frame:
            try:
                self.grid_frame.destroy()
            except:
                pass
        
        rows, cols = self.app.calculate_rows_cols(len(plugins), max_cols=max_cols, min_cols=min_cols)
        self._current_cols = len(cols)
        self._current_max_cols = max_cols
        
        self.grid_frame = self.app.create_grid(
            frame=self._content_frame,
            row=0,
            column=0,
            plugins=plugins,
            color="transparent",
            sticky="nsew",
            max_cols=max_cols,
            min_cols=min_cols,
        )
        
        for index, plugin in enumerate(plugins):
            r = index // len(cols)
            c = index % len(cols)
            self.app.create_plugin_card(
                r, c, self.grid_frame, plugin, 
                show_description=True,
                truncate=True
            )
