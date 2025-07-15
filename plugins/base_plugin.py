"""
This module contains the BasePlugin class, which is the base class for all plugins.
The BasePlugin class provides common functionality and attributes that are shared by all plugins.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

from PIL import Image
import customtkinter
import os 

class BasePlugin:
    """
    Base class for plugins, providing common functionality and attributes.
    """

    def __init__(self, id, order, name, status, description, supported_systems, translations, icon_light_path, icon_dark_path):
        """
        Initialize the BasePlugin with the given attributes.

        :param id: The unique identifier for the plugin.
        :param order: The order in which the plugin should be displayed.
        :param name: The name of the plugin.
        :param status: The current status of the plugin.
        :param description: A brief description of the plugin.
        :param supported_systems: A list of systems supported by the plugin.
        :param translations: A dictionary of translations for the plugin.
        :param icon_light_path: Path to the light mode icon.
        :param icon_dark_path: Path to the dark mode icon.
        """
        self.id = id
        self.order = order
        self.name = name
        self.status = status
        self.description = description
        self.supported_systems = supported_systems
        self.translations = translations
        self.icon_light = icon_light_path
        self.icon_dark = icon_dark_path
        self.icon = self.create_icon(size=(20, 20))
        self.icon_alert = None
        self.button = None

    def create_main_screen(self):
        """
        Create the main screen for the plugin.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses should implement this method")

    def set_id(self, id):
        """
        Set the ID of the plugin.

        :param id: The new ID for the plugin.
        """
        self.id = id

    def get_id(self):
        """
        Get the ID of the plugin.

        :return: The ID of the plugin.
        """
        return self.id

    def set_name(self, name):
        """
        Set the name of the plugin.

        :param name: The new name for the plugin.
        """
        self.name = name

    def get_name(self):
        """
        Get the name of the plugin.

        :return: The name of the plugin.
        """
        return self.name

    def set_status(self, status):
        """
        Set the status of the plugin.

        :param status: The new status for the plugin.
        """
        self.status = status

    def get_status(self):
        """
        Get the status of the plugin.

        :return: The status of the plugin.
        """
        return self.status

    def set_translations(self, translations):
        """
        Set the translations for the plugin.

        :param translations: The new translations for the plugin.
        """
        self.translations = translations

    def get_translations(self):
        """
        Get the translations for the plugin.

        :return: The translations of the plugin.
        """
        return self.translations

    def create_icon(self, size):
        """
        Create an icon for the plugin using the provided size.

        :param size: The size of the icon.
        :return: The created icon.
        """
        light_image = Image.open(self.icon_light)
        dark_image = Image.open(self.icon_dark)
        return customtkinter.CTkImage(light_image=dark_image, dark_image=light_image, size=size)

    def get_icon(self):
        """
        Get the icon of the plugin.

        :return: The icon of the plugin.
        """
        return self.icon

    def get_icon_alert(self):
        """
        Get the alert icon based on the plugin's status.

        :return: The alert icon.
        """
        icon_map = {
            "Ok": "check.png",
            "Critical": "critical.png",
            "Error": "error.png",
            "Info": "info.png",
            "Warning": "warning.png"
        }
        symbols_img_paths = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "resources", "icons")
        icon_filename = icon_map.get(self.status)
        self.icon_light = f"{symbols_img_paths}/{icon_filename}"
        self.icon_dark = f"{symbols_img_paths}/{icon_filename}"
        self.icon_alert = self.create_icon(size=(16, 16))
        return self.icon_alert

    def set_button(self, button):
        """
        Set the button associated with the plugin.

        :param button: The new button for the plugin.
        """
        self.button = button

    def get_button(self):
        """
        Get the button associated with the plugin.

        :return: The button of the plugin.
        """
        return self.button

    def get_supported_systems(self):
        """
        Get the systems supported by the plugin.

        :return: The supported systems.
        """
        return self.supported_systems

    def set_supported_systems(self, supported_systems):
        """
        Set the systems supported by the plugin.

        :param supported_systems: The new supported systems.
        """
        self.supported_systems = supported_systems

    def set_description(self, description):
        """
        Set the description of the plugin.

        :param description: The new description for the plugin.
        """
        self.description = description

    def get_description(self):
        """
        Get the description of the plugin.

        :return: The description of the plugin.
        """
        return self.description
    