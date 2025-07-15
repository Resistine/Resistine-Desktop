## @file plugins/dashboard/main.py
## @package dashboard_plugin
## @namespace dashboard_plugin
## @class dashboard_plugin::Plugin

"""
This script is used to display the dashboard plugin in a grid format.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""


from plugins.base_plugin import BasePlugin
import customtkinter
from PIL import Image
import os
from plugins.plugin_manager import PluginManager
from utils import functions as myfunctions 

class Plugin(BasePlugin):
    """
    @brief Plugin class for the Dashboard plugin.
    Plugin class for the Dashboard plugin, that allows users to view the plugins in a grid format
    """
    def __init__(self, app):
        """
        @brief Initialize the Dashboard plugin.
        Initialize the Dashboard plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="001",
            order=1,
            name="Dashboard",
            status="OK",
            description="This plugin allows you to view the dashboard.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Dashboard", "ES": "Panel", "FR": "Tableau de bord"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "home_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "home_dark.png"),
        )
        self.app = app
    

    def create_main_screen(self):
        """
        @brief Create the main screen for the Dashboard plugin.
        Create the main screen for the Dashboard plugin.
        """
        
        self.main_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=3)

        # Title frame (20% of the total height)
        self.title_frame = customtkinter.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        self.title_frame.grid(row=0, column=0, sticky="nsew")
        self.title_frame.grid_columnconfigure(0, weight=1)
        self.title_frame.grid_rowconfigure(0, weight=1)

        self.title_label = customtkinter.CTkLabel(
            self.title_frame,
            text="You are protected",
            font=customtkinter.CTkFont(size=30, weight="bold")
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")

        # Load plugins
        if not hasattr(self.app, 'plugin_list') or not self.app.plugin_list:
            self.plugin_list = PluginManager(self.app).plugins
        else:
            self.plugin_list = self.app.plugin_list
        self.plugins = self.plugin_list[1:]
        #self.plugins = PluginManager(self.app).plugins[1:]
        #gettings rows and columns
        rows, cols = myfunctions.calculate_rows_cols(len(self.plugins))

        # Add scroll if more than 2 rows
        if len(rows) > 2:
            self.canvas = customtkinter.CTkCanvas(self.main_frame)
            self.scrollbar = customtkinter.CTkScrollbar(self.main_frame, command=self.canvas.yview)
            parent_bg = self.main_frame.master.cget("background")
            self.canvas.configure(yscrollcommand=self.scrollbar.set, background=parent_bg, highlightthickness=0)

            # Set the background color for the scrollable_frame
            self.scrollable_frame = customtkinter.CTkFrame(self.canvas, fg_color="transparent")
            self.scrollable_frame.bind(
                "<Configure>",
                lambda e: self.canvas.configure(
                    scrollregion=self.canvas.bbox("all")
                )
            )

            self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
            self.canvas.grid(row=1, column=0, sticky="nsew")
            #self.scrollbar.configure(background=parent_bg, highlightthickness=0)
            self.scrollbar.grid(row=1, column=1, sticky="ns")

            # Ensure the main_frame expands to fill the available space
            self.main_frame.grid_rowconfigure(1, weight=1)
            self.main_frame.grid_columnconfigure(0, weight=1)

            # Ensure the scrollable_frame expands to fill the canvas
            self.scrollable_frame.grid_columnconfigure(0, weight=1)
            self.scrollable_frame.grid_rowconfigure(0, weight=1)

            # Ensure the canvas expands to fill the available space
            self.canvas.bind(
                "<Configure>",
                lambda e: self.canvas.itemconfig(
                    self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", width=e.width)
                )
            )

            self.grid_frame = myfunctions.create_grid(self.scrollable_frame, 0, 0, self.plugins, "transparent", "nsew")

        else:
            # Grid frame dynamically created for the plugins
            self.grid_frame = myfunctions.create_grid(self.main_frame, 1, 0, self.plugins, "transparent", "nsew")
            
        # Ex: 5 plugins, 2 rows (0, 1), 3 columns (0, 1, 2), first plugin should be located in position 0,0, then 0,1, 0,2, 1,0, 1,1

        # Place plugins in the grid
        for index, plugin in enumerate(self.plugins):
            row = index // len(cols)
            col = index % len(cols)
            myfunctions.create_option(row, col, self.grid_frame, plugin)      

        return self.main_frame
