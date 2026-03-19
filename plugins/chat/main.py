# @file plugins/chat/main.py
"""
Chat Plugin
The plugin allows users to chat with the AI assistant.
Author: Peres J., P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import random  # noqa: F401 — used for suggestion shuffling
import sys
import tkinter as tk

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from utils import settings
from utils.logger import logger

# Pool of suggestion prompts shown on the welcome screen.
# 4 are picked at random each time the chat is opened.
_SUGGESTION_POOL = [
    "Explain what a zero-day exploit is",
    "How do I harden my Linux server?",
    "Analyze a suspicious network log",
    "What are common phishing indicators?",
    "How does a man-in-the-middle attack work?",
    "What is the MITRE ATT&CK framework?",
    "Explain the difference between IDS and IPS",
    "How do I set up a firewall with iptables?",
    "What are best practices for password security?",
    "How do I detect lateral movement in a network?",
    "Explain DNS tunneling and how to detect it",
    "What is ransomware and how do I prevent it?",
]


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
                os.path.dirname(os.path.realpath(__file__)), "chat_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "chat_dark.png"
            ),
        )
        self.app = app
        self.client = None
        self.animated_text = None
        self.conversation_history = []
        self.reinitialize_client()
        self.status = self.get_status()

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _is_dark_mode(self) -> bool:
        appearance_mode = customtkinter.get_appearance_mode()
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

    def _theme_color(self, key, fallback_light, fallback_dark):
        """Resolve a Theme color from the JSON theme, falling back to provided values."""
        pair = ThemeManager.theme.get("Theme", {}).get(key)
        is_dark = self._is_dark_mode()
        if pair and isinstance(pair, (list, tuple)) and len(pair) == 2:
            return pair[1] if is_dark else pair[0]
        return fallback_dark if is_dark else fallback_light

    def _bind_mousewheel(self, widget):
        """Bind mouse wheel scrolling to a text widget with smooth inertia."""
        from utils.scroll import (
            CHAT_SCROLL_DELTA, CHAT_WHEEL_SCALE, CHAT_VEL_CLAMP,
            CHAT_VEL_THRESHOLD, CHAT_VEL_DECAY,
        )

        state = {"vel": 0.0, "job": None}

        def _step():
            try:
                if not widget.winfo_exists():
                    state["job"] = None
                    return
                v = state["vel"]
                if abs(v) < CHAT_VEL_THRESHOLD:
                    state["vel"] = 0.0
                    state["job"] = None
                    return
                before = widget.yview()
                scroll_px = int(round(v)) or (1 if v > 0 else -1)
                widget.yview_scroll(scroll_px, "pixels")
                after = widget.yview()
                if abs(after[0] - before[0]) < 0.0001:
                    state["vel"] = 0.0
                    state["job"] = None
                    return
                state["vel"] *= CHAT_VEL_DECAY
                state["job"] = widget.after(8, _step)
            except Exception:
                state["job"] = None

        def _add_velocity(delta):
            state["vel"] += delta
            state["vel"] = max(-CHAT_VEL_CLAMP, min(CHAT_VEL_CLAMP, state["vel"]))
            if state["job"] is None:
                state["job"] = widget.after(1, _step)

        def on_mousewheel(event):
            if sys.platform == "darwin":
                _add_velocity(-1 * event.delta * CHAT_WHEEL_SCALE)
            else:
                _add_velocity(-1 * (event.delta / 120) * CHAT_WHEEL_SCALE)
            return "break"

        widget.bind("<MouseWheel>", on_mousewheel, add="+")
        if sys.platform != "darwin":
            widget.bind("<Button-4>", lambda e: (_add_velocity(-CHAT_SCROLL_DELTA), "break")[-1], add="+")
            widget.bind("<Button-5>", lambda e: (_add_velocity(CHAT_SCROLL_DELTA), "break")[-1], add="+")

        # Prevent horizontal scrolling
        widget.configure(xscrollcommand=lambda *args: None)

        # Stash _add_velocity so _bind_scroll_redirect_to_chat can reuse it
        self._chat_add_velocity = _add_velocity

    def _bind_scroll_redirect_to_chat(self, chat_tw, widget):
        """Bind scroll events on widget to feed into the main chat scroll state.

        Same velocity / animation loop as _bind_mousewheel — no independent
        state, so multiple widgets can't stack and double the speed.
        """
        add_vel = getattr(self, "_chat_add_velocity", None)
        if add_vel is None:
            return

        from utils.scroll import CHAT_SCROLL_DELTA, CHAT_WHEEL_SCALE

        def on_wheel(event):
            if sys.platform == "darwin":
                add_vel(-1 * event.delta * CHAT_WHEEL_SCALE)
            else:
                add_vel(-1 * (event.delta / 120) * CHAT_WHEEL_SCALE)
            return "break"

        widget.bind("<MouseWheel>", on_wheel, add="+")
        if sys.platform != "darwin":
            widget.bind("<Button-4>", lambda e: (add_vel(-CHAT_SCROLL_DELTA), "break")[-1], add="+")
            widget.bind("<Button-5>", lambda e: (add_vel(CHAT_SCROLL_DELTA), "break")[-1], add="+")

    # ------------------------------------------------------------------
    # Client / API
    # ------------------------------------------------------------------

    def check_status(self):
        """Check if the Chat plugin is ready to use."""
        if self.client:
            return "OK"
        return "Warning"

    def reinitialize_client(self, notify: bool = False):
        """Reinitialize the OpenAI client with the current API key.

        Args:
            notify: If True, show a user-visible notification on failure.
                    Defaults to False to avoid spurious toasts during plugin
                    loading (e.g. when the Store enumerates all plugins).
        """
        api_key = settings.get_secret("chat", "openai_api_key")
        self.base_url = settings.get("chat", "openai_base_url")
        self.session_id = None  # Reset session ID on re-init

        # Determine model and history setup based on base_url
        if self.base_url:
            self.model = "ministral-3:14b"
            self.conversation_history = []
        else:
            self.model = "gpt-4o"
            self.conversation_history = [
                {
                    "role": "system",
                    "content": "You are SOC Copilot specialized in cybersecurity.",
                }
            ]

        if api_key:
            try:
                kwargs = {"api_key": api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                from openai import OpenAI
                self.client = OpenAI(**kwargs)
                logger.info("Chat plugin: OpenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Chat plugin: Failed to initialize OpenAI client: {e}")
                if notify:
                    self.app.show_notification(f"Chat Init Error: {e}", type="error")
                self.client = None
        else:
            self.client = None
            logger.warning(
                "Chat plugin: No OpenAI API key found. Chat functionality disabled."
            )

    def send_message_to_chatgpt(self, message: str):
        """Send a message to the ChatGPT model and yield the response chunks."""
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
            messages = [{"role": "user", "content": message}]
            self.conversation_history.append({"role": "user", "content": message})

            extra_body = {}
            if self.session_id:
                extra_body["session_id"] = self.session_id

            logger.debug(
                f"Chat plugin: Sending request to Custom API (Model: {self.model}, Session: {self.session_id}, Stream: True): {messages}"
            )

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

                if hasattr(chunk, "session_id"):
                    self.session_id = chunk.session_id

            logger.debug(
                f"Chat plugin: Received full response from Custom API: {full_response}"
            )

        else:
            self.conversation_history.append({"role": "user", "content": message})

            logger.debug(
                f"Chat plugin: Sending request to OpenAI API (Model: {self.model}, Stream: True): {self.conversation_history}"
            )

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

        self.conversation_history.append(
            {"role": "assistant", "content": full_response}
        )

    # ------------------------------------------------------------------
    # Bubble rendering
    # ------------------------------------------------------------------

    def _get_chat_width(self):
        """Return usable pixel width inside the chat textbox."""
        tw = self.chat_box._textbox
        tw.update_idletasks()
        w = tw.winfo_width()
        if w <= 1:
            w = 800
        padx = int(str(tw.cget("padx") or 0))
        return max(w - padx * 2 - 4, 300)

    def render_user_bubble(self, user_message):
        """Render the user's message bubble flush to the right edge."""
        tw = self.chat_box._textbox
        available = self._get_chat_width()

        # Fixed-width tk.Frame — pack_propagate(False) keeps the width,
        # pack(side="right") pushes the bubble to the right edge.
        container = tk.Frame(
            tw, highlightthickness=0, bd=0,
            width=available, bg=tw.cget("background"),
        )
        container.pack_propagate(False)

        bubble = customtkinter.CTkFrame(
            container, fg_color="#0D5394", corner_radius=18,
        )
        bubble.pack(side="right", padx=(0, 12))

        label = customtkinter.CTkLabel(
            bubble,
            text=user_message,
            fg_color="transparent",
            text_color="#FFFFFF",
            wraplength=min(600, int(available * 0.75)),
            font=customtkinter.CTkFont(family="Inter", size=15),
            justify="left",
            anchor="w",
        )
        label.pack(padx=18, pady=11)

        # Height must be set after children are measured
        container.update_idletasks()
        container.configure(height=bubble.winfo_reqheight())

        tw.window_create("end", window=container, padx=0, pady=10)
        tw.insert("end", "\n")

        # Redirect scroll events from user bubble widgets to the chat textbox
        self._bind_scroll_redirect_to_chat(tw, container)
        self._bind_scroll_redirect_to_chat(tw, bubble)
        self._bind_scroll_redirect_to_chat(tw, label)

        # Keep container width in sync when window resizes
        def _sync(event, c=container):
            try:
                w = self._get_chat_width()
                c.configure(width=w)
            except tk.TclError:
                pass
        tw.bind("<Configure>", _sync, add="+")

    def render_assistant_bubble_markdown(self, message):
        """Render the assistant's response at full available width."""
        from plugins.chat.markdown_bubble import MarkdownBubble

        tw = self.chat_box._textbox
        available = self._get_chat_width()

        # Give MarkdownBubble the correct width from the start
        bubble = MarkdownBubble(self.chat_box, message, width=available)

        tw.window_create("end", window=bubble, padx=0, pady=10)
        tw.insert("end", "\n")

        # Force a proper resize after embedding
        def _finalize():
            w = self._get_chat_width()
            if w > 1 and hasattr(bubble, "_update_width"):
                bubble._update_width(w)
        tw.after(50, _finalize)

    # ------------------------------------------------------------------
    # Welcome screen (shown when no conversation history)
    # ------------------------------------------------------------------

    def _build_no_api_key_screen(self, parent):
        """Build a centered overlay telling the user to configure an API key."""
        is_dark = self._is_dark_mode()
        secondary_color = self._theme_color("text_secondary", "#6B7280", "#9CA3AF")
        resistine_blue = "#0D5394"
        error_color = self._theme_color("", "#B45309", "#FBBF24")

        self._no_key_frame = customtkinter.CTkFrame(parent, fg_color="transparent")
        self._no_key_frame.place(relx=0.5, rely=0.45, anchor="center")

        icon_label = customtkinter.CTkLabel(
            self._no_key_frame,
            text="\u26A0",
            font=customtkinter.CTkFont(size=36),
            text_color=error_color,
        )
        icon_label.pack(pady=(0, 8))

        title_label = customtkinter.CTkLabel(
            self._no_key_frame,
            text="API Key Required",
            font=customtkinter.CTkFont(family="Inter", size=20, weight="bold"),
            text_color="#ffffff" if is_dark else "#000000",
        )
        title_label.pack(pady=(0, 6))

        desc_label = customtkinter.CTkLabel(
            self._no_key_frame,
            text="Add your OpenAI API key in Settings to start chatting.",
            font=customtkinter.CTkFont(family="Inter", size=14),
            text_color=secondary_color,
        )
        desc_label.pack(pady=(0, 20))

        settings_btn = customtkinter.CTkButton(
            self._no_key_frame,
            text="Open Settings",
            font=customtkinter.CTkFont(family="Inter", size=13, weight="bold"),
            fg_color=resistine_blue,
            hover_color="#1565B0",
            text_color="#ffffff",
            corner_radius=10,
            height=40,
            width=160,
            command=self._open_settings,
        )
        settings_btn.pack()

    def _open_settings(self):
        """Navigate to the Settings plugin."""
        try:
            settings_plugin = next(
                (p for p in self.app.plugin_list if p.get_name() == "Settings"), None
            )
            if settings_plugin:
                self.app.select_frame_by_name(
                    "frame_Settings", button=settings_plugin.get_button()
                )
        except Exception:
            pass

    def _build_welcome_screen(self, parent):
        """Build a centered welcome overlay with greeting + suggestion chips."""
        is_dark = self._is_dark_mode()
        fg_color = "#ffffff" if is_dark else "#000000"
        secondary_color = self._theme_color("text_secondary", "#6B7280", "#9CA3AF")
        card_bg = "#1A1A1C" if is_dark else "#ffffff"
        card_hover = "#242426" if is_dark else "#F0F0F5"
        resistine_blue = "#0D5394"

        self._welcome_frame = customtkinter.CTkFrame(parent, fg_color="transparent")
        self._welcome_frame.place(relx=0.5, rely=0.45, anchor="center")

        # Greeting
        greeting_label = customtkinter.CTkLabel(
            self._welcome_frame,
            text="Resistine AI",
            font=customtkinter.CTkFont(family="Inter", size=26, weight="bold"),
            text_color=resistine_blue,
        )
        greeting_label.pack(pady=(0, 4))

        subtitle_label = customtkinter.CTkLabel(
            self._welcome_frame,
            text="Your AI security assistant. Ask me anything.",
            font=customtkinter.CTkFont(family="Inter", size=14),
            text_color=secondary_color,
        )
        subtitle_label.pack(pady=(0, 28))

        # Pick 4 random suggestions from the pool
        suggestions = random.sample(
            _SUGGESTION_POOL, min(4, len(_SUGGESTION_POOL))
        )

        chips_frame = customtkinter.CTkFrame(
            self._welcome_frame, fg_color="transparent"
        )
        chips_frame.pack()

        # 2x2 grid of suggestion chips
        for i, suggestion in enumerate(suggestions):
            row = i // 2
            col = i % 2

            chip = customtkinter.CTkButton(
                chips_frame,
                text=suggestion,
                font=customtkinter.CTkFont(family="Inter", size=13),
                fg_color=card_bg,
                hover_color=card_hover,
                text_color=fg_color,
                corner_radius=10,
                border_width=1,
                border_color=self._theme_color("divider_color", "#E5E7EB", "#2A2A2A"),
                height=44,
                width=260,
                anchor="w",
                command=lambda s=suggestion: self._use_suggestion(s),
            )
            chip.grid(row=row, column=col, padx=6, pady=6)

    def _use_suggestion(self, text):
        """Fill the input bar with a suggestion and send it."""
        if hasattr(self, "_welcome_frame") and self._welcome_frame:
            self._welcome_frame.destroy()
            self._welcome_frame = None
        self.chat_entry.delete(0, "end")
        self.chat_entry.insert(0, text)
        self.send_message()

    def _clear_conversation(self):
        """Reset conversation history and rebuild the screen."""
        if self.base_url:
            self.conversation_history = []
        else:
            self.conversation_history = [
                {
                    "role": "system",
                    "content": "You are SOC Copilot specialized in cybersecurity.",
                }
            ]
        self.session_id = None
        # Destroy and recreate the screen
        if hasattr(self, "second_frame") and self.second_frame:
            self.second_frame.destroy()
        frame = self.create_main_screen()
        frame.grid(row=0, column=1, sticky="nsew")

    # ------------------------------------------------------------------
    # Main screen
    # ------------------------------------------------------------------

    def create_main_screen(self):
        """Create the main screen for the Chat plugin."""
        self.corner_radius = ThemeManager.theme.get("Theme", {}).get(
            "corner_radius", 12
        )

        is_dark = self._is_dark_mode()
        resistine_blue = "#0D5394"
        fg_color = "#ffffff" if is_dark else "#000000"
        secondary_color = self._theme_color("text_secondary", "#6B7280", "#9CA3AF")
        input_bg = "#1A1A1C" if is_dark else "#F5F5F7"
        border_color = self._theme_color("divider_color", "#E5E7EB", "#2A2A2A")

        # --- Root frame ---
        self.second_frame = customtkinter.CTkFrame(
            self.app,
            corner_radius=0,
            fg_color="transparent",
        )
        self.second_frame.grid_columnconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(0, weight=1)

        # --- Chat area ---
        chat_wrapper = customtkinter.CTkFrame(
            self.second_frame, fg_color="transparent"
        )
        chat_wrapper.grid(row=0, column=0, sticky="nsew")
        chat_wrapper.grid_columnconfigure(0, weight=1)
        chat_wrapper.grid_rowconfigure(0, weight=1)

        self.chat_box = customtkinter.CTkTextbox(
            chat_wrapper,
            wrap="word",
            font=customtkinter.CTkFont(family="Inter", size=14, weight="normal"),
            fg_color="transparent",
            text_color=fg_color,
            corner_radius=0,
            border_width=0,
            activate_scrollbars=True,
        )
        # Bottom padding reserves space so content doesn't render behind
        # the input bar overlaid at the bottom of second_frame.
        self.chat_box.grid(row=0, column=0, padx=0, pady=(0, 58), sticky="nsew")
        self.chat_box._textbox.configure(padx=8)

        # Enable mouse wheel scrolling
        self._bind_mousewheel(self.chat_box._textbox)

        # Tags for styling
        self.chat_box._textbox.tag_config(
            "assistant",
            foreground=fg_color,
            justify="left",
            lmargin1=0,
            lmargin2=0,
        )
        self.chat_box._textbox.tag_config("error", foreground="#EF4444")

        self.chat_box.configure(state="disabled")

        # Animated text handler
        from plugins.chat.animated_text import AnimatedText
        self.animated_text = AnimatedText(
            self.chat_box._textbox,
            character_delay=0.02,
            line_delay=0.5,
        )

        # Restore history or show welcome screen
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
                self.render_assistant_bubble_markdown(content)

        self.chat_box.configure(state="disabled")

        # Show appropriate overlay when no history
        self._welcome_frame = None
        self._no_key_frame = None
        has_api_key = self.client is not None

        if not has_history:
            if has_api_key:
                self._build_welcome_screen(chat_wrapper)
            else:
                self._build_no_api_key_screen(chat_wrapper)

        # --- Input bar (overlaid at bottom, full width) ---
        input_bar = customtkinter.CTkFrame(
            self.second_frame,
            fg_color=input_bg,
            corner_radius=22,
            border_width=1,
            border_color=border_color,
        )
        input_bar.place(
            relx=0.5, rely=1.0, anchor="s", relwidth=0.98, y=-14
        )
        input_bar.grid_columnconfigure(0, weight=1)
        input_bar.grid_columnconfigure(1, weight=0)

        self.chat_entry = customtkinter.CTkEntry(
            input_bar,
            placeholder_text="Message Resistine AI...",
            corner_radius=20,
            border_width=0,
            height=44,
            font=customtkinter.CTkFont(family="Inter", size=14),
            fg_color="transparent",
            text_color=fg_color,
            placeholder_text_color="#8ea8c6" if is_dark else "#9aa5b1",
        )
        self.chat_entry.grid(row=0, column=0, padx=(16, 4), pady=0, sticky="ew")

        self.send_button = customtkinter.CTkButton(
            input_bar,
            text="\u2191",
            command=self.send_message,
            corner_radius=18,
            height=36,
            width=36,
            font=customtkinter.CTkFont(size=18, weight="bold"),
            fg_color=resistine_blue,
            hover_color="#1565B0",
            text_color="#ffffff",
        )
        self.send_button.grid(row=0, column=1, padx=(0, 6), pady=6)

        self.chat_entry.bind("<Return>", lambda event: self.send_message())

        # Disable input when no API key is configured
        if not has_api_key:
            self.chat_entry.configure(
                state="disabled",
                placeholder_text="API key required \u2014 see Settings",
            )
            self.send_button.configure(state="disabled", fg_color="#6B7280")

        return self.second_frame

    # ------------------------------------------------------------------
    # Send message
    # ------------------------------------------------------------------

    def send_message(self):
        """Send a message and render: user bubble + animated assistant reply."""
        user_message = self.chat_entry.get().strip()
        if not user_message:
            return

        # Remove welcome screen if visible
        if hasattr(self, "_welcome_frame") and self._welcome_frame:
            self._welcome_frame.destroy()
            self._welcome_frame = None

        self.chat_entry.delete(0, "end")
        self.chat_box.configure(state="normal")

        # Render User Bubble
        self.render_user_bubble(user_message)

        self.chat_box.update_idletasks()
        self.chat_box._textbox.see("end")

        # Insert marker for streaming text
        self.chat_box._textbox.insert("end", "", "assistant")
        start_index = self.chat_box._textbox.index("end-1c")

        disable_animation = settings.get("chat", "disable_animation", False)
        full_response = ""

        try:
            stream = self.send_message_to_chatgpt(user_message)

            for chunk in stream:
                full_response += chunk

                if not disable_animation:
                    self.chat_box.configure(state="normal")
                    self.chat_box._textbox.insert("end", chunk, "assistant")
                    self.chat_box.configure(state="disabled")
                    self.chat_box._textbox.see("end")
                    self.chat_box.update_idletasks()

            # Finalize: Replace streamed text with formatted MarkdownBubble
            self.chat_box.configure(state="normal")

            if not disable_animation:
                end_index = self.chat_box._textbox.index("end-1c")
                self.chat_box._textbox.delete(start_index, end_index)

            self.render_assistant_bubble_markdown(full_response)

            self.chat_box.configure(state="disabled")
            self.chat_box._textbox.see("end")

        except Exception as e:
            self.chat_box.configure(state="normal")
            self.chat_box._textbox.insert("end", f"Error: {str(e)}\n\n\n", "error")
            self.chat_box.configure(state="disabled")
            self.chat_box._textbox.see("end")
