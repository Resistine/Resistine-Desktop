## @file plugins/chat/main.py
## @package chat_plugin
## @namespace chat_plugin
## @class chat_plugin::Plugin

"""
This module contains the main functionality for the Chat plugin.
The plugin allows users to chat with the AI assistant.
Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import sys

import customtkinter
from openai import OpenAI

from plugins.base_plugin import BasePlugin
from plugins.chat.animated_text import AnimatedText
from utils import settings


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
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "chat_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "chat_dark.png"
            ),
        )
        self.app = app
        self.client: OpenAI | None = None
        self.animated_text: AnimatedText | None = None
        self.reinitialize_client()

    def reinitialize_client(self):
        """Reinitialize the OpenAI client with the current API key."""
        api_key = settings.get_secret("chat", "openai_api_key")
        if api_key:
            try:
                self.client = OpenAI(api_key=api_key)
                print("Chat plugin: OpenAI client initialized successfully")
            except Exception as e:
                print(f"Chat plugin: Failed to initialize OpenAI client: {e}")
                self.client = None
        else:
            self.client = None
            print("Chat plugin: No OpenAI API key found. Chat functionality disabled.")

    def send_message_to_chatgpt(self, message: str) -> str:
        """Send a message to the ChatGPT model and return the response."""
        # Try to reinitialize if client is None (in case key was just added)
        if not self.client:
            self.reinitialize_client()

        if not self.client:
            return (
                "Error: OpenAI API key not configured or invalid. "
                "Please check your settings."
            )

        messages = [
            {
                "role": "system",
                "content": "You are SOC Copilot specialized in cybersecurity.",
            },
            {"role": "user", "content": message},
        ]

        response = self.client.chat.completions.create(
            model="gpt-4o", messages=messages, temperature=0.5, max_tokens=150
        )

        return response.choices[0].message.content

    def create_main_screen(self):
        """Create the main screen for the Chat plugin (bubbles + animated typing)."""
        self.second_frame = customtkinter.CTkFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.second_frame.grid_columnconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(1, weight=0)

        # Helper: determine effective dark mode (supports System on macOS)
        appearance_mode = customtkinter.get_appearance_mode()

        def is_dark_mode() -> bool:
            if appearance_mode == "Dark":
                return True
            if appearance_mode == "Light":
                return False
            if sys.platform == "darwin":
                try:
                    import subprocess

                    result = subprocess.run(
                        ["defaults", "read", "-g", "AppleInterfaceStyle"],
                        capture_output=True,
                        text=True,
                    )
                    return result.returncode == 0 and "Dark" in result.stdout
                except Exception:
                    return False
            return False

        resistine_blue = "#0D5394"
        is_dark = is_dark_mode()
        panel_bg = "#1A1A1A" if is_dark else "#ffffff"
        fg_color = "#ffffff" if is_dark else "#000000"

        self.chat_box = customtkinter.CTkTextbox(
            self.second_frame,
            wrap="word",
            font=customtkinter.CTkFont(size=15, weight="normal"),
            fg_color="transparent",
            text_color=fg_color,
            corner_radius=20,
            border_width=0,
        )
        self.chat_box.grid(row=0, column=0, padx=20, pady=(30, 10), sticky="nsew")

        # Center content with dynamic margins
        def update_text_margins(event=None):
            box_width = self.chat_box.winfo_width()
            if box_width > 1:
                side_margin = int(box_width * 0.15)
                self.chat_box._textbox.configure(padx=side_margin)

        self.chat_box.bind("<Configure>", update_text_margins)
        self.chat_box._textbox.configure(padx=100)

        # Tags for styling
        self.chat_box._textbox.tag_config(
            "assistant",
            foreground=fg_color,
            justify="left",
            lmargin1=0,
            lmargin2=0,
        )
        self.chat_box._textbox.tag_config("error", foreground="#ff4444")

        self.chat_box.configure(state="disabled")

        # Animated text handler for AI responses (animate into CTkTextbox's internal tk.Text)
        self.animated_text = AnimatedText(
            self.chat_box._textbox,
            character_delay=0.02,
            line_delay=0.5,
        )
        # Initial welcome message
        self.chat_box.configure(state="normal")
        welcome_msg = "Hello! I am Resistine, your AI security assistant. How can I help you today?"
        self.chat_box._textbox.insert("1.0", f"Resistine AI: {welcome_msg}\n\n\n", "assistant")
        self.chat_box.configure(state="disabled")

        # Input container
        container = customtkinter.CTkFrame(
            self.second_frame,
            corner_radius=12,
            fg_color="transparent",
        )
        container.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=0)

        self.chat_entry = customtkinter.CTkEntry(
            container,
            placeholder_text="Message Resistine AI...",
            corner_radius=12,
            border_width=0,
            height=40,
            font=customtkinter.CTkFont(size=14),
            fg_color=panel_bg,
            text_color=fg_color,
            placeholder_text_color="#8ea8c6" if is_dark else "#9aa5b1",
        )
        self.chat_entry.grid(row=0, column=0, padx=(0, 20), pady=0, sticky="ew")

        self.send_button = customtkinter.CTkButton(
            container,
            text="Send",
            command=self.send_message,
            corner_radius=12,
            height=40,
            width=80,
            font=customtkinter.CTkFont(size=14, weight="bold"),
            fg_color=resistine_blue,
            hover_color="#1565B0",
            text_color="#ffffff",
        )
        self.send_button.grid(row=0, column=1, padx=0, pady=12, sticky="ew")
        self.chat_entry.bind("<Return>", lambda event: self.send_message())

        return self.second_frame

    def send_message(self):
        """Send a message and render: user bubble + animated assistant reply."""
        user_message = self.chat_entry.get().strip()
        if not user_message:
            return

        appearance_mode = customtkinter.get_appearance_mode()
        if appearance_mode == "Dark":
            bubble_color = "#3A3A3C"
            bubble_text_color = "#ffffff"
        elif appearance_mode == "Light":
            bubble_color = "#E5E5EA"
            bubble_text_color = "#000000"
        else:
            bubble_color = "#E5E5EA"
            bubble_text_color = "#000000"
            if sys.platform == "darwin":
                try:
                    import subprocess

                    result = subprocess.run(
                        ["defaults", "read", "-g", "AppleInterfaceStyle"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0 and "Dark" in result.stdout:
                        bubble_color = "#3A3A3C"
                        bubble_text_color = "#ffffff"
                except Exception:
                    pass

        self.chat_box.configure(state="normal")

        # USER bubble as an embedded window
        bubble_frame = customtkinter.CTkFrame(
            self.chat_box,
            fg_color=bubble_color,
            corner_radius=15,
        )
        bubble_text = customtkinter.CTkLabel(
            bubble_frame,
            text=user_message,
            fg_color="transparent",
            text_color=bubble_text_color,
            wraplength=400,
            font=customtkinter.CTkFont(size=15),
            justify="left",
            anchor="w",
        )
        bubble_text.pack(padx=12, pady=9)

        self.chat_box._textbox.window_create("end", window=bubble_frame, padx=10, pady=10)
        self.chat_box._textbox.insert("end", "\n\n\n")

        # Right-align the bubble line
        self.chat_box._textbox.tag_add("user_align", "end-4l", "end-3l")
        self.chat_box._textbox.tag_config("user_align", justify="right")

        self.chat_box.update_idletasks()
        insertion_point = self.chat_box._textbox.index("end")

        try:
            response = self.send_message_to_chatgpt(user_message)

            if not self.animated_text:
                self.animated_text = AnimatedText(self.chat_box._textbox)

            current_end = self.chat_box._textbox.index("end")
            if current_end != insertion_point:
                insertion_point = current_end

            def on_animation_complete():
                self.chat_box._textbox.insert("end", "\n\n\n")
                self.chat_box.configure(state="disabled")
                self.chat_box._textbox.see("end")

            self.animated_text.set_insertion_point(insertion_point)
            self.animated_text.start_animation(
                response,
                insert_tag="assistant",
                on_complete=on_animation_complete,
            )
        except Exception as e:
            self.chat_box._textbox.insert("end", f"Error: {str(e)}\n\n\n", "error")
            self.chat_box.configure(state="disabled")
            self.chat_box._textbox.see("end")

        self.chat_entry.delete(0, "end")
