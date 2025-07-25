## @file plugins/chat/main.py
## @package chat_plugin
## @namespace chat_plugin
## @class chat_plugin::Plugin

"""
This module contains the main functionality for the Chat plugin.
The plugin allows users to chat with the AI assistant.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import tkinter as tk
import customtkinter
from PIL import Image
from openai import OpenAI
import os
from plugins.base_plugin import BasePlugin


class Plugin(BasePlugin):
    """
    @brief Plugin class for the Chat plugin.
    Plugin class for the Chat plugin, that allows users to chat with the AI assistant
    """
    def __init__(self, app):
        """
        @brief Initialize the Chat plugin.
        Initialize the Chat plugin with the specified parameters.
        :param app: Main application object.
        """
        super().__init__(
            id="002",
            order=2,
            name="Chat",
            status="OK",
            description="This plugin allows you to chat with the AI assistant.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Chat", "ES": "Chat", "FR": "Chat"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "chat_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "chat_dark.png"),
        )
        self.app = app
        self.client = OpenAI(
            #replace with your api key
            api_key= "X"
        )

    def send_message_to_chatgpt(self, message):
        """
        Send a message to the ChatGPT model and return the response.
        """
        messages = [
            {"role": "system", "content": "You are SOC Copilot specialized in cybersecurity."},
        ]

        messages.append({"role": "user", "content": message})

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,
            max_tokens=150
        )

        chat_message = response.choices[0].message.content
        messages.append({"role": "assistant", "content": chat_message})
        return chat_message

    def create_main_screen(self):
        """
        @brief Create the main screen for the Chat plugin.
        Create the main screen for the Chat plugin.
        """
        self.second_frame = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.second_frame.grid_columnconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(1, weight=0)

        # Determine the current theme and set colors accordingly
        if customtkinter.get_appearance_mode() == "Light":
            chat_bg_color = "white"
            chat_fg_color = "white"
            insert_bg_color = "white"
            button_fg_color = "#007CB4"
            button_hover_color = "#005F8A"
            text_color = "black"
        else:
            chat_bg_color = "#2e2e2e"
            chat_fg_color = "#2e2e2e"
            insert_bg_color = "#2e2e2e"
            button_fg_color = "#005F8A"
            button_hover_color = "#003F5A"
            text_color = "white"

        self.chat_box = tk.Text(self.second_frame, wrap="word", bg=chat_bg_color, fg=chat_fg_color, insertbackground=insert_bg_color, padx=10, pady=10)
        self.chat_box.grid(row=0, column=0, padx=20, pady=10, sticky="nsew")

        # Configure tag for blue color
        self.chat_box.tag_configure("blue", foreground="#007CB4", font=("Inter", 12))
        self.chat_box.tag_configure("user", foreground=text_color, font=("Inter", 12))

        container = customtkinter.CTkFrame(self.second_frame, corner_radius=0, fg_color="transparent")
        container.grid(row=1, column=0, padx=15, pady=15, sticky="ew")

        # Insert initial message
        self.chat_box.insert("end", "Resistine AI: ", "blue")
        self.chat_box.insert("end", "Hello, I'm your AI assistant, how can I help you?\n", "user")

        container.grid_columnconfigure(0, weight=8)
        container.grid_columnconfigure(1, weight=2)

        self.chat_entry = customtkinter.CTkEntry(container, placeholder_text="Type your message here...")
        self.chat_entry.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="ew")

        # Send button
        self.send_button = customtkinter.CTkButton(container, text="Send", command=self.send_message, fg_color=button_fg_color, hover_color=button_hover_color)
        self.send_button.grid(row=0, column=1, padx=0, pady=0, sticky="ew")
        self.chat_entry.bind("<Return>", lambda event: self.send_message())

        return self.second_frame

    def send_message(self):
        """
        Send a message from the chat entry to ChatGPT and display the response in the chat box.
        
        This method retrieves the user's message from the chat entry widget, sends it to the ChatGPT model,
        and then inserts both the user's message and the AI's response into the chat box. The user's message
        is tagged with "user" and the AI's response is tagged with "blue" for the name and "user" for the response.
        Finally, it clears the chat entry widget.
        """
        user_message = self.chat_entry.get()
        response = self.send_message_to_chatgpt(user_message)
        self.chat_box.insert("end", f"You: {user_message}\n", "user")
        self.chat_box.insert("end", "Resistine AI: ", "blue")  # Insert the name with the tag
        self.chat_box.insert("end", f"{response}\n", "user")  # Insert the response without the tag
        self.chat_entry.delete(0, "end")
