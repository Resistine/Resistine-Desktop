## @file plugins/settings/main.py
## @package settings_plugin
## @namespace settings_plugin
## @class settings_plugin::Plugin

"""
This file contains the main plugin class for the Settings plugin.
The plugin allows users to configure their account settings.
Author: Resistine
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

from plugins.base_plugin import BasePlugin
import customtkinter
import os 

class Plugin(BasePlugin):
    """
    @brief Plugin class for the Settings plugin.
    Plugin class for the Settings plugin, that allows user to configure their account settings.
    """
    def __init__(self, app):
        """
        @brief Initialize the Settings plugin.
        Initialize the Settings plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="010",
            order=10,
            name="Settings",
            status="OK",
            description="This plugin allows you to configure your account settings.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Settings", "ES": "Configuracion", "FR": "Paramètres"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings_dark.png"),
        )
        self.app = app

    def create_main_screen(self):
        """
        @brief Create the main screen for the Settings plugin.
        Create the main screen for the Settings plugin.
        """
        self.frame_5 = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.frame_5.grid_columnconfigure(0, weight=1)
        self.frame_5.grid_rowconfigure((0, 1, 2), weight=1)

        self.profile_name_label = customtkinter.CTkLabel(self.frame_5, text="Name: Javier Peres", font=customtkinter.CTkFont(size=20))
        self.profile_name_label.grid(row=0, column=0, padx=20, pady=10)

        email_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "utils", "email-settings.txt")
        with open(email_file_path, 'r') as file:
            email = file.read().strip()

        self.profile_email_label = customtkinter.CTkLabel(self.frame_5, text=f"Email: {email}", font=customtkinter.CTkFont(size=20))
        self.profile_email_label.grid(row=1, column=0, padx=20, pady=10)

        return self.frame_5

  