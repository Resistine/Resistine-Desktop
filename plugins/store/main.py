## @file plugins/store/main.py
## @package store_plugin
## @namespace store_plugin
##@class store_plugin::Plugin
""""
Store plugin for the Resistine application.
This plugin allows users to download and install new plugins from the store.
Author: Peres J.
Copyright (c) Crescentiva 2025
Licensed under the Apache License 2.0
"""

from plugins.base_plugin import BasePlugin
import customtkinter
from PIL import Image
import os
import webbrowser
from plugins.plugin_manager import PluginManager

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
            order=4,
            name="Store",
            status="OK",
            description="This plugin allows you to download and install new plugins.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Store", "ES": "Tienda", "FR": "Magasin"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "store_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "store_dark.png"),
        )
        self.app = app

    def create_main_screen(self):
        """
        @brief Create the main screen for the Store plugin.
        Create the main screen for the Store plugin.
        """
        self.main_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=4)

        # Title frame (20% of the total height)
        self.title_frame = customtkinter.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        self.title_frame.grid(row=0, column=0, sticky="nsew")
        self.title_frame.grid_columnconfigure(0, weight=1)

        self.title_label = customtkinter.CTkLabel(
            self.title_frame,
            text="Store",
            font=customtkinter.CTkFont(size=30, weight="bold")
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=20)

        # Grid frame (80% of the total height)
        self.grid_frame = customtkinter.CTkFrame(self.main_frame, corner_radius=0, fg_color="transparent")
        self.grid_frame.grid(row=1, column=0, sticky="nsew")
        self.grid_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_frame.grid_rowconfigure((0, 1, 2), weight=1)

        def resize_image(image_path, size):
            """
            Resize an image to the specified size.
            
            :param image_path: Path to the image file.
            :param size: Tuple specifying the new size (width, height).
            :return: Resized image.
            """
            image = Image.open(image_path)
            resized_image = image.resize(size, Image.Resampling.LANCZOS)
            return resized_image

        def create_option(row, column, main_icon_light_path, main_icon_dark_path, title, main_event):
            """
            Create an option in the grid with an icon and title.
            
            :param row: Row position in the grid.
            :param column: Column position in the grid.
            :param main_icon_light_path: Path to the light mode icon.
            :param main_icon_dark_path: Path to the dark mode icon.
            :param title: Title of the option.
            :param main_event: Event to be triggered on click.
            """
            # Create a frame for the option
            frame = customtkinter.CTkFrame(self.grid_frame, corner_radius=10, fg_color=("gray75", "gray25"))
            frame.grid(row=row, column=column, padx=20, pady=20, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure((1, 1), weight=10)

            # Create a container frame for the main icon and title
            icon_title_frame = customtkinter.CTkFrame(frame, fg_color="transparent")

            # Center the icon_title_frame vertically and horizontally
            icon_title_frame.grid(row=0, column=0, padx=10, pady=(20, 20), sticky="nsew")
            icon_title_frame.grid_columnconfigure(0, weight=1)
            icon_title_frame.grid_rowconfigure(0, weight=1)
            icon_title_frame.grid_rowconfigure(1, weight=1)

            # Resize the main icon
            resized_main_icon_light = resize_image(main_icon_light_path, (90, 90))
            resized_main_icon_dark = resize_image(main_icon_dark_path, (90, 90))

            # Main icon
            main_icon_image = customtkinter.CTkImage(
            light_image=Image.open(main_icon_light_path),
            dark_image=Image.open(main_icon_dark_path),
            size=(30, 30)
            )
            main_icon_label = customtkinter.CTkLabel(icon_title_frame, image=main_icon_image, text="")
            main_icon_label.grid(row=0, column=0, padx=(10, 10), pady=(30, 10))

            # Title label
            title_label = customtkinter.CTkLabel(icon_title_frame, text=title, font=customtkinter.CTkFont(size=14, weight="bold"))
            title_label.grid(row=1, column=0, padx=0, pady=5)

            # Make the entire frame clickable to open the URL
            frame.bind("<Button-1>", lambda event: main_event())
            main_icon_label.bind("<Button-1>", lambda event: main_event())
            title_label.bind("<Button-1>", lambda event: main_event())

        # For testing purposes
        web_url = "https://resistine.crescentiva.com/"
        file_id = "1PjHT9rgXSenzT7lBTy6CijPMn0kqNpAG"
        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        def event_redirect(url):
            """
            Redirect to the specified URL in a new browser tab.
            
            :param url: URL to redirect to.
            """
            webbrowser.open_new_tab(url)

        def event_download(url):
            """
            Download a plugin from the specified URL.
            
            :param url: URL to download the plugin from.
            """
            PluginManager(self.app).download_plugin(url)

        
        product_image_light_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "store_dark.png")
        product_image_dark_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "store_light.png")
        
        # Create options
        create_option(0, 0, product_image_light_path , product_image_dark_path, "Odoo", lambda: event_redirect(web_url))
        create_option(0, 1, product_image_light_path, product_image_dark_path, "ClamAV", lambda: event_redirect(web_url))
        create_option(0, 2, product_image_light_path, product_image_dark_path, "Wazuh",  lambda: event_redirect("https://10.49.11.10/"))
        create_option(1, 0, product_image_light_path, product_image_dark_path, "VPN", lambda: event_redirect(web_url))
        create_option(1, 1, product_image_light_path, product_image_dark_path, "Calculator", lambda: event_download(direct_url))
        create_option(1, 2, product_image_light_path, product_image_dark_path, "Plugin 2", lambda: event_download(direct_url))

        return self.main_frame

  