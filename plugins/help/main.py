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
#import html2text
from tkinterweb import HtmlFrame



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

        self.help_label = customtkinter.CTkLabel(self.main_container, text="Help", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.help_label.grid(row=0, column=0, padx=20, pady=10, sticky="new")

         # Load and parse the Markdown content
        markdown_file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "help.md")
        with open(markdown_file_path, "r", encoding="utf-8") as file:
            markdown_content = file.read()
        html_body = markdown.markdown(markdown_content, extensions=["fenced_code", "tables"])

        # Render HTML inside the app
        self.html_view = HtmlFrame(self.main_container, messages_enabled=False)
        html_doc = f"""
            <html>
            <head>
              <meta charset="utf-8">
              <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 12px; }}
                h1, h2, h3 {{ margin-top: 1em; }}
                code, pre {{ background: #f5f5f5; padding: 2px 4px; }}
                ul, ol {{ padding-left: 1.2em; }}
                a {{ color: #0b5fff; }}
              </style>
            </head>
            <body>{html_body}</body>
            </html>
        """
        # base_url makes relative links/images work
        base_url = os.path.dirname(markdown_file_path)
        self.html_view.load_html(html_doc, base_url=base_url)
        self.html_view.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        return self.main_container

    def open_docs(self):
        webbrowser.open("https://resistine.crescentiva.com/")