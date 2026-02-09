# @file plugins/chat/main.py
"""
Chat Plugin
The plugin allows users to chat with the AI assistant.
Author: Peres J., P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import sys

import customtkinter
from openai import OpenAI

from plugins.base_plugin import BasePlugin
from plugins.chat.animated_text import AnimatedText
from plugins.chat.markdown_bubble import MarkdownBubble
from utils import settings
from utils.logger import logger


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
            version="2025.01.01",
            order=2,
            name="Chat",
            status=None,
            description="This plugin allows you to chat with the AI assistant.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Chat", "ES": "Chat", "FR": "Chat"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "chat_light.svg"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "chat_dark.svg"
            ),
        )
        self.app = app
        self.client: OpenAI | None = None
        self.animated_text: AnimatedText | None = None
        self.conversation_history = []
        self.reinitialize_client()
        self.status = self.get_status()

    def check_status(self):
        """Check if the Chat plugin is ready to use."""
        if self.client:
            return "OK"
        return "Warning"

    def reinitialize_client(self):
        """Reinitialize the OpenAI client with the current API key."""
        api_key = settings.get_secret("chat", "openai_api_key")
        self.base_url = settings.get("chat", "openai_base_url")
        self.session_id = None  # Reset session ID on re-init

        # Determine model and history setup based on base_url
        if self.base_url:
            self.model = "ministral-3:14b"
            # Custom URL: Stateful, history managed by server, no system prompt needed here
            self.conversation_history = []
        else:
            self.model = "gpt-4o"
            # Default URL: Stateless client-side, need system prompt
            self.conversation_history = [
                {
                    "role": "system",
                    "content": "You are SOC Copilot specialized in cybersecurity.",
                }
            ]

        if api_key:
            try:
                # Initialize client, including base_url if provided
                kwargs = {"api_key": api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self.client = OpenAI(**kwargs)
                logger.info("Chat plugin: OpenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Chat plugin: Failed to initialize OpenAI client: {e}")
                self.app.show_notification(f"Chat Init Error: {e}", type="error")
                self.client = None
        else:
            self.client = None
            logger.warning(
                "Chat plugin: No OpenAI API key found. Chat functionality disabled."
            )
            self.app.show_notification(
                "Chat disabled: No API key found", type="warning"
            )

    def send_message_to_chatgpt(self, message: str):
        """Send a message to the ChatGPT model and yield the response chunks."""
        # Try to reinitialize if client is None (in case key was just added)
        if not self.client:
            self.reinitialize_client()

        if not self.client:
            yield (
                "Error: OpenAI API key not configured or invalid. "
                "Please check your settings."
            )
            return

        full_response = ""

        if self.base_url:
            # --- Custom URL (Stateful) Logic ---
            messages = [{"role": "user", "content": message}]

            # Append user message to local history for display persistence
            self.conversation_history.append({"role": "user", "content": message})

            extra_body = {}
            if self.session_id:
                extra_body["session_id"] = self.session_id

            logger.debug(
                f"Chat plugin: Sending request to Custom API (Model: {self.model}, Session: {self.session_id}, Stream: True): {messages}"
            )

            # Send request with stream=True
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                extra_body=extra_body,
                stream=True,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content

                # Extract session_id if present in chunk (often in last chunk or as extra field)
                if hasattr(chunk, "session_id"):
                    self.session_id = chunk.session_id

            logger.debug(
                f"Chat plugin: Received full response from Custom API: {full_response}"
            )

        else:
            # --- Default OpenAI (Stateless) Logic ---
            # Append user message to full history
            self.conversation_history.append({"role": "user", "content": message})

            logger.debug(
                f"Chat plugin: Sending request to OpenAI API (Model: {self.model}, Stream: True): {self.conversation_history}"
            )

            # Send request with full history and stream=True
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=self.conversation_history,
                stream=True,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    yield content

            logger.debug(
                f"Chat plugin: Received full response from OpenAI API: {full_response}"
            )

        # Append assistant response to history
        self.conversation_history.append(
            {"role": "assistant", "content": full_response}
        )

    def render_user_bubble(self, user_message):
        """Render the user's message bubble."""
        # Helper: determine effective dark mode (supports System on macOS)
        appearance_mode = customtkinter.get_appearance_mode()
        bubble_color = "#E5E5EA"
        bubble_text_color = "#000000"

        if appearance_mode == "Dark":
            bubble_color = "#3A3A3C"
            bubble_text_color = "#ffffff"
        elif appearance_mode == "Light":
            bubble_color = "#E5E5EA"
            bubble_text_color = "#000000"
        else:
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

        # USER bubble as an embedded window
        bubble_frame = customtkinter.CTkFrame(
            self.chat_box,
            fg_color=bubble_color,
            corner_radius=getattr(self, "corner_radius", 15),
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

        self.chat_box._textbox.window_create(
            "end", window=bubble_frame, padx=10, pady=10
        )
        self.chat_box._textbox.insert("end", "\n\n\n")

        # Right-align the bubble line
        self.chat_box._textbox.tag_add("user_align", "end-4l", "end-3l")
        self.chat_box._textbox.tag_config("user_align", justify="right")

    def render_assistant_bubble_markdown(self, message):
        """Render the assistant's response using MarkdownBubble."""
        bubble = MarkdownBubble(self.chat_box, message)

        # Ensure we insert at the end
        self.chat_box._textbox.mark_set("insert", "end")
        insert_index = self.chat_box._textbox.index("insert")

        # Insert into text box
        self.chat_box._textbox.window_create(
            "end", window=bubble, padx=0, pady=10, stretch=1
        )
        self.chat_box._textbox.insert("end", "\n\n\n")

        # Use index range for tag
        line_start = insert_index.split(".")[0] + ".0"
        line_end = insert_index.split(".")[0] + ".end"

        # Apply strict left justify
        self.chat_box._textbox.tag_add("assistant_align", line_start, line_end)
        self.chat_box._textbox.tag_config("assistant_align", justify="left")

    def create_main_screen(self):
        """Create the main screen for the Chat plugin (bubbles + animated typing)."""
        # Get theme corner radius
        from customtkinter import ThemeManager

        self.corner_radius = ThemeManager.theme.get("Theme", {}).get(
            "corner_radius", 15
        )

        self.second_frame = customtkinter.CTkFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )

        self.second_frame.grid_columnconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(1, weight=0)

        # Build Appearance mode detection
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


        # Container for chat messages (centered, 70% width)
        chat_container = customtkinter.CTkFrame(self.second_frame, fg_color="transparent", height=100)
        chat_container.grid(row=0, column=0, sticky="nsew", pady=(30, 10))
        chat_container.grid_columnconfigure(0, weight=1)
        chat_container.grid_rowconfigure(0, weight=1)
        chat_container.grid_propagate(True)

        # Inner centered chat wrapper
        chat_wrapper = customtkinter.CTkFrame(chat_container, fg_color="transparent")
        chat_wrapper.place(relx=0.5, rely=0.5, relwidth=0.7, relheight=1.0, anchor="center")
        chat_wrapper.grid_columnconfigure(0, weight=1)
        chat_wrapper.grid_rowconfigure(0, weight=1)

        self.chat_box = customtkinter.CTkTextbox(
            chat_wrapper,
            wrap="word",
            font=customtkinter.CTkFont(size=15, weight="normal"),
            fg_color="transparent",
            text_color=fg_color,
            corner_radius=self.corner_radius,
            border_width=0,
        )
        self.chat_box.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")

        # Center content with dynamic margins
        def update_text_margins(event=None):
            box_width = self.chat_box.winfo_width()
            if box_width > 1:
                side_margin = int(box_width * 0.05)
                self.chat_box._textbox.configure(padx=side_margin)

        self.chat_box.bind("<Configure>", update_text_margins)
        self.chat_box._textbox.configure(padx=20)

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

        # Restore history or show welcome message
        self.chat_box.configure(state="normal")

        has_history = False
        for msg in self.conversation_history:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                continue

            has_history = True
            if role == "user":
                self.render_user_bubble(content)
            elif role == "assistant":
                # Render previous assistant messages using MarkdownBubble
                self.render_assistant_bubble_markdown(content)

        if not has_history:
            # Initial welcome message
            welcome_msg = "Hello! I am Resistine, your AI security assistant. How can I help you today?"
            self.chat_box._textbox.insert(
                "1.0", f"Resistine AI: {welcome_msg}\n\n\n", "assistant"
            )

        self.chat_box.configure(state="disabled")

        # Container for input (centered, same 70% width as chat)
        input_container = customtkinter.CTkFrame(self.second_frame, fg_color="transparent")
        input_container.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        input_container.grid_columnconfigure(0, weight=1)
        input_container.grid_propagate(True)

        # Inner centered input wrapper
        input_wrapper = customtkinter.CTkFrame(input_container, fg_color="transparent")
        input_wrapper.place(relx=0.5, rely=0.5, relwidth=0.7, anchor="center")
        input_wrapper.grid_columnconfigure(0, weight=1)

        container = customtkinter.CTkFrame(
            input_wrapper,
            corner_radius=self.corner_radius,
            fg_color="transparent",
        )
        container.grid(row=0, column=0, padx=0, pady=0, sticky="ew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=0)

        self.chat_entry = customtkinter.CTkEntry(
            container,
            placeholder_text="Message Resistine AI...",
            corner_radius=self.corner_radius,
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
            corner_radius=self.corner_radius,
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

        # Clear entry and enable chat box for insertion
        self.chat_entry.delete(0, "end")
        self.chat_box.configure(state="normal")

        # Render User Bubble
        self.render_user_bubble(user_message)

        self.chat_box.update_idletasks()
        self.chat_box._textbox.see("end")

        # Initialize Assistant Bubble (Empty)
        self.chat_box._textbox.insert("end", "", "assistant")
        start_index = self.chat_box._textbox.index("end-1c")

        # Check animation setting - if disabled, we buffer and show at once
        disable_animation = settings.get("chat", "disable_animation", False)
        buffered_response = ""
        full_response = ""

        try:
            # Consume stream
            stream = self.send_message_to_chatgpt(user_message)

            for chunk in stream:
                full_response += chunk

                if disable_animation:
                    buffered_response += chunk
                else:
                    self.chat_box.configure(state="normal")
                    self.chat_box._textbox.insert("end", chunk, "assistant")
                    self.chat_box.configure(state="disabled")
                    self.chat_box._textbox.see("end")
                    self.chat_box.update_idletasks()

            if disable_animation:
                # Still show text briefly if disabled, or just skip to replace?
                # Let's direct render the markdown if disabled.
                pass

            # Finalize: Replace text with MarkdownBubble
            self.chat_box.configure(state="normal")

            if not disable_animation:
                # Delete the raw text we streamed
                end_index = self.chat_box._textbox.index("end-1c")
                # Ensure we strictly delete what we inserted.
                # start_index was set before streaming.
                self.chat_box._textbox.delete(start_index, end_index)

            # Insert MarkdownBubble
            self.render_assistant_bubble_markdown(full_response)

            self.chat_box.configure(state="disabled")
            self.chat_box._textbox.see("end")

        except Exception as e:
            self.chat_box.configure(state="normal")
            self.chat_box._textbox.insert("end", f"Error: {str(e)}\n\n\n", "error")
            self.chat_box.configure(state="disabled")
            self.chat_box._textbox.see("end")
