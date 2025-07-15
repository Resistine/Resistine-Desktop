## @file plugins/help/main.py
## @package help_plugin
## @namespace help_plugin
## @class help_plugin::Plugin

"""
This is the main file for the Help plugin, that provides help documentation.
Author: Peres J.
Copyright (c) Crescentiva 2025
Licensed under the Apache License 2.0
"""

from plugins.base_plugin import BasePlugin
import customtkinter
import os
import webbrowser
import markdown
import html2text



class Plugin(BasePlugin):
    """
    @brief Plugin class for the Help plugin.
    Plugin class for the Help plugin, that provides help documentation.
    """
    def __init__(self, app):
        """
        @brief Initialize the Help plugin.
        Initialize the Help plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="009",
            order=9,
            name="Help",
            status="OK",
            description="This plugin provides help documentation.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Help", "ES": "Ayuda", "FR": "Aide"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "help_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "help_dark.png"),
        )
        self.app = app
        
    def create_main_screen(self):
        """
        @brief Create the main screen for the Help plugin.
        Create the main screen for the Help plugin.
        """
        self.main_container = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)  # 20% for help_label
        self.main_container.grid_rowconfigure(1, weight=8)  # 70% for markdown_viewer
        self.main_container.grid_rowconfigure(2, weight=1)  # 10% for open_docs_button

        self.help_label = customtkinter.CTkLabel(self.main_container, text="Help", font=customtkinter.CTkFont(size=20))
        self.help_label.grid(row=0, column=0, padx=20, pady=10, sticky="new")

        # Load and parse the Markdown content
        markdown_file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "help.md")
        with open(markdown_file_path, "r") as file:
            markdown_content = file.read()
        html_content = markdown.markdown(markdown_content)
        plain_text_content = html2text.html2text(html_content)

        # Create a Text widget to display the parsed Markdown content
        self.markdown_viewer = customtkinter.CTkTextbox(self.main_container, wrap="word")
        self.markdown_viewer.insert("1.0", plain_text_content)
        self.markdown_viewer.configure(state="disabled")
        self.markdown_viewer.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        self.open_docs_button = customtkinter.CTkButton(self.main_container, text="Open Documentation", command=self.open_docs)
        self.open_docs_button.grid(row=2, column=0, padx=20, pady=10)

        return self.main_container

    def open_docs(self):
        webbrowser.open("https://resistine.crescentiva.com/")