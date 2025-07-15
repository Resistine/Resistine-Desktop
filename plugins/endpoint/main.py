## @file plugins/endpoint/main.py
## @package endpoint_plugin
## @namespace endpoint_plugin
## @class endpoint_plugin::Plugin

"""
This is the main file of the Endpoint plugin.
The plugin allows users to view the endpoints.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

from plugins.base_plugin import BasePlugin
import customtkinter
import os 

class Plugin(BasePlugin):
    """
    @brief Plugin class for the Endpoint plugin.
    Plugin class for the Endpoint plugin, that allows user interact with resistine endpoints.
    """
    def __init__(self, app):
        """
        @brief Initialize the Endpoint plugin.
        Initialize the Endpoint plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="003",
            order=3,
            name="Endpoint",
            status="OK",
            description="This plugin allows you to view the endpoints.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Endpoint", "ES": "Endpoint", "FR": "Endpoint"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "add_user_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "add_user_dark.png"),
        )
        self.app = app

    def create_main_screen(self):
        """
        @brief Create the main screen for the Endpoint plugin.
        Create the main screen for the Endpoint plugin.
        """
        self.main_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure((0, 1, 2), weight=1)

        self.profile_name_label = customtkinter.CTkLabel(self.main_frame, text="Endpoint View", font=customtkinter.CTkFont(size=20))
        self.profile_name_label.grid(row=0, column=0, padx=20, pady=10)


        return self.main_frame
