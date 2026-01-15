"""
This module contains the BasePlugin class, which is the base class for all plugins.
The BasePlugin class provides common functionality and attributes that are shared by all plugins.
Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from PIL import Image
import customtkinter
import os
from io import BytesIO

try:
    from cairosvg import svg2png
    HAS_SVG = True
except ImportError:
    HAS_SVG = False 

class BasePlugin:
    """
    Base class for plugins, providing common functionality and attributes.
    """

    # Status map for standardizing status strings
    status_map = {
        "ok": "OK",
        "info": "Info",
        "warning": "Warning",
        "error": "Error",
        "critical": "Critical"
    }    

    def __init__(self, id, version, order, name, status, description, supported_systems, translations, icon_light_path, icon_dark_path, uninstall_enabled=True):
        """
        Initialize the BasePlugin with the given attributes.

        :param id: The unique identifier for the plugin.
        :param version: The version of the plugin.
        :param order: The order in which the plugin should be displayed.
        :param name: The name of the plugin.
        :param status: The current status of the plugin.
        :param description: A brief description of the plugin.
        :param supported_systems: A list of systems supported by the plugin.
        :param translations: A dictionary of translations for the plugin.
        :param icon_light_path: Path to the light mode icon.
        :param icon_dark_path: Path to the dark mode icon.
        :param uninstall_enabled: Whether the plugin can be uninstalled.
        """
        self.id = id
        self.version = version
        self.order = order
        self.name = name
        self.status = status
        self.description = description
        self.supported_systems = supported_systems
        self.translations = translations
        self.icon_light = icon_light_path
        self.icon_dark = icon_dark_path
        self.uninstall_enabled = uninstall_enabled
        self.icon = self.create_icon(size=(20, 20))
        self.icon_alert = None
        self.button = None
        self.app = None # Will be set by subclasses or manager

    def uninstall(self):
        """
        Uninstall the plugin via the application's PluginManager.
        """
        if not self.uninstall_enabled:
            return "Uninstall is not enabled for this plugin."
        
        if hasattr(self, "app") and self.app:
            return self.app.get_plugin_manager().uninstall_plugin(self)
        return "Application instance not found; cannot uninstall."

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

    def check_status(self):
        """
        Operational check for the plugin. 
        Subclasses should override this to provide real-time status.
        :return: Standard status string (OK, Info, Warning, Error, Critical)
        """
        return self.status

    def get_status(self):
        """
        Get the current status of the plugin, with error handling.
        :return: Standard status string.
        """
        try:
            status = self.check_status()
            if status is None:
                return None
            # Normalize status to standard capitalization
            return self.status_map.get(status.lower(), status)
        except Exception as e:
            from utils.logger import logger
            logger.error(f"Status check failed for plugin {self.name}: {e}")
            return "Warning"

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
        Supports both PNG and SVG formats.

        :param size: The size of the icon.
        :return: The created icon.
        """
        def load_icon(path, size):
            from utils.logger import logger
            
            # Check if SVG version exists (even if path ends with .png)
            if path.lower().endswith('.png'):
                svg_path = path[:-4] + '.svg'
                if os.path.exists(svg_path) and HAS_SVG:
                    try:
                        logger.info(f"📊 Loading SVG icon: {os.path.basename(svg_path)}")
                        png_data = svg2png(url=svg_path, output_width=size[0], output_height=size[1])
                        logger.info(f"✅ Successfully loaded SVG: {os.path.basename(svg_path)}")
                        return Image.open(BytesIO(png_data))
                    except Exception as e:
                        logger.warning(f"⚠️ SVG loading failed for {os.path.basename(svg_path)}: {e}, using PNG")
                        return Image.open(path)
                else:
                    # No SVG found or no SVG support, use PNG
                    return Image.open(path)
            
            # Path already ends with .svg
            elif path.lower().endswith('.svg'):
                if HAS_SVG:
                    try:
                        logger.info(f"📊 Loading SVG icon: {os.path.basename(path)}")
                        png_data = svg2png(url=path, output_width=size[0], output_height=size[1])
                        logger.info(f"✅ Successfully loaded SVG: {os.path.basename(path)}")
                        return Image.open(BytesIO(png_data))
                    except Exception as e:
                        logger.warning(f"⚠️ SVG loading failed for {os.path.basename(path)}: {e}")
                        # Try PNG fallback
                        png_path = path[:-4] + '.png'
                        if os.path.exists(png_path):
                            logger.info(f"📄 Using PNG fallback: {os.path.basename(png_path)}")
                            return Image.open(png_path)
                else:
                    logger.warning(f"⚠️ SVG support not available for {os.path.basename(path)}")
                    png_path = path[:-4] + '.png'
                    if os.path.exists(png_path):
                        logger.info(f"📄 Using PNG fallback: {os.path.basename(png_path)}")
                        return Image.open(png_path)
            
            # Default: try to open as-is
            return Image.open(path)
        
        light_image = load_icon(self.icon_light, size)
        dark_image = load_icon(self.icon_dark, size)
        return customtkinter.CTkImage(light_image=dark_image, dark_image=light_image, size=size)

    def get_icon(self):
        """
        Get the icon of the plugin (20x20 for sidebar).

        :return: The icon of the plugin.
        """
        return self.icon

    def get_icon_large(self):
        """
        Get a larger icon of the plugin (50x50 for dashboard/store cards).

        :return: A larger icon of the plugin.
        """
        return self.create_icon(size=(50, 50))

    def get_icon_alert(self):
        """
        Get the alert icon based on the plugin's status.

        :return: The alert icon.
        """
        current_status = self.get_status()
        icon_map = {
            "OK": "check.png",
            "Critical": "critical.png",
            "Error": "error.png",
            "Info": "info.png",
            "Warning": "warning.png"
        }
        symbols_img_paths = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "resources", "icons")
        icon_filename = icon_map.get(current_status, "warning.png")
        self.icon_light = f"{symbols_img_paths}/{icon_filename}"
        self.icon_dark = f"{symbols_img_paths}/{icon_filename}"
        self.icon_alert = self.create_icon(size=(50, 50))
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
    