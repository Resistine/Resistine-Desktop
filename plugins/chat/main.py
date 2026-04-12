"""Resistine AI Chat plugin."""
from __future__ import annotations

import os
import sys
import customtkinter
from plugins.base_plugin import BasePlugin
from plugins.chat.bubble import (
    AssistantBubble, BubbleRow, UserBubble, assistant_width, user_width)
from plugins.chat.fonts import _is_dark_mode
from plugins.chat.streaming import StreamController
from plugins.chat.welcome_screen import ApiKeyMissingScreen, WelcomeScreen
from utils import settings
from utils.emoji_entry import EmojiEntry
from utils.logger import logger

_RESISTINE_BLUE = "#0D5394"
_SYSTEM_PROMPT = "You are SOC Copilot specialized in cybersecurity."
_ICON_DIR = os.path.dirname(os.path.realpath(__file__))
_SYS_MSG = {"role": "system", "content": _SYSTEM_PROMPT}


class Plugin(BasePlugin):
    """Chat plugin -- lets users talk to an OpenAI-compatible AI assistant."""

    def __init__(self, app):
        super().__init__(
            id="002", version="2025.01.01", order=2, name="Chat", status=None,
            description="This plugin allows you to chat with the AI assistant.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Chat", "ES": "Chat", "FR": "Chat"},
            icon_light_path=os.path.join(_ICON_DIR, "chat_light.png"),
            icon_dark_path=os.path.join(_ICON_DIR, "chat_dark.png"))
        self.app = app
        self.client = None
        self.conversation_history: list[dict] = []
        self._bubble_rows: list[BubbleRow] = []
        self._stream_ctrl: StreamController | None = None
        self._welcome_frame: WelcomeScreen | ApiKeyMissingScreen | None = None
        self.reinitialize_client()
        self.status = self.get_status()

    def check_status(self):
        """Return ``'OK'`` when the OpenAI client is ready, else ``'Warning'``."""
        return "OK" if self.client else "Warning"

    def reinitialize_client(self, notify: bool = False):
        """Rebuild the OpenAI client from the current settings."""
        api_key = settings.get_secret("chat", "openai_api_key")
        self.base_url = settings.get("chat", "openai_base_url")
        self.session_id = None
        if self.base_url:
            self.model, self.conversation_history = "ministral-3:14b", []
        else:
            self.model = "gpt-4o"
            self.conversation_history = [dict(_SYS_MSG)]
        if not api_key:
            self.client = None
            logger.warning("Chat plugin: No API key found. Chat disabled.")
            return
        try:
            kwargs: dict = {"api_key": api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            from openai import OpenAI
            self.client = OpenAI(**kwargs)
            logger.info("Chat plugin: OpenAI client initialized successfully")
        except Exception as e:
            logger.error(f"Chat plugin: Failed to initialize client: {e}")
            if notify:
                self.app.show_notification(f"Chat Init Error: {e}", type="error")
            self.client = None

    def send_message_to_chatgpt(self, message: str):
        """Send *message* to the AI and yield response chunks (generator)."""
        if not self.client:
            self.reinitialize_client()
        if not self.client:
            yield ("Error: OpenAI API key not configured or invalid. "
                   "Please check your settings.")
            return
        self.conversation_history.append({"role": "user", "content": message})
        full = ""
        if self.base_url:
            extra_body: dict = {}
            if self.session_id:
                extra_body["session_id"] = self.session_id
            stream = self.client.chat.completions.create(
                model=self.model, extra_body=extra_body, stream=True,
                messages=[{"role": "user", "content": message}])
        else:
            stream = self.client.chat.completions.create(
                model=self.model, messages=self.conversation_history, stream=True)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                full += chunk.choices[0].delta.content
                yield chunk.choices[0].delta.content
            if self.base_url and hasattr(chunk, "session_id"):
                self.session_id = chunk.session_id
        self.conversation_history.append({"role": "assistant", "content": full})

    def _clear_conversation(self):
        """Reset conversation history and rebuild the chat screen."""
        self.conversation_history = [] if self.base_url else [dict(_SYS_MSG)]
        self.session_id = None
        self._bubble_rows.clear()
        if hasattr(self, "second_frame") and self.second_frame:
            self.second_frame.destroy()
        self.create_main_screen().grid(row=0, column=1, sticky="nsew")

    def create_main_screen(self):
        """Build and return the chat plugin UI."""
        is_dark = _is_dark_mode()
        self.second_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent")
        self.second_frame.grid_columnconfigure(0, weight=1)
        self.second_frame.grid_rowconfigure(0, weight=1)
        sb_thumb = "#555555" if is_dark else "#BBBBBB"
        sb_hover = "#777777" if is_dark else "#999999"
        self.chat_scroll = customtkinter.CTkScrollableFrame(
            self.second_frame, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=sb_thumb,
            scrollbar_button_hover_color=sb_hover)
        self.chat_scroll.grid(row=0, column=0, padx=0, pady=(0, 62), sticky="nsew")
        self._bubble_rows.clear()
        self._welcome_frame = None
        self._bottom_spacer: customtkinter.CTkFrame | None = None
        self._current_asst_bubble: AssistantBubble | None = None
        self._restore_history(is_dark)
        self._build_input_bar(is_dark)
        self.chat_scroll.bind("<Configure>", self._on_resize, add="+")
        return self.second_frame

    def _restore_history(self, is_dark: bool) -> None:
        has_history = False
        for msg in self.conversation_history:
            role, content = msg.get("role"), msg.get("content", "")
            if role == "system":
                continue
            has_history = True
            if role == "user":
                self._add_user_bubble(content, is_dark)
            elif role == "assistant":
                self._add_assistant_bubble(is_dark, md=content)
        if has_history:
            return
        if self.client is not None:
            self._welcome_frame = WelcomeScreen(
                self.chat_scroll, self._use_suggestion, is_dark)
        else:
            self._welcome_frame = ApiKeyMissingScreen(
                self.chat_scroll, self._open_settings, is_dark)
        self._welcome_frame.pack(expand=True, pady=(80, 0))

    def _build_input_bar(self, is_dark: bool) -> None:
        fg = "#ffffff" if is_dark else "#000000"
        bg, brd = ("#1A1A1C", "#2A2A2A") if is_dark else ("#F5F5F7", "#E5E7EB")
        bar = customtkinter.CTkFrame(
            self.second_frame, fg_color=bg,
            corner_radius=22, border_width=1, border_color=brd)
        bar.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.98, y=-14)
        bar.grid_columnconfigure(0, weight=1)
        self.chat_entry = EmojiEntry(
            bar, placeholder_text="Message Resistine AI...",
            corner_radius=20, border_width=0, height=44,
            font=customtkinter.CTkFont(family="Inter", size=14),
            fg_color="transparent", text_color=fg,
            placeholder_text_color="#8ea8c6" if is_dark else "#9aa5b1")
        self.chat_entry.grid(row=0, column=0, padx=(16, 4), pady=0, sticky="ew")
        self.send_button = customtkinter.CTkButton(
            bar, text="\u2191", command=self.send_message,
            corner_radius=18, height=36, width=36,
            font=customtkinter.CTkFont(size=18, weight="bold"),
            fg_color=_RESISTINE_BLUE, hover_color="#1565B0", text_color="#ffffff")
        self.send_button.grid(row=0, column=1, padx=(0, 6), pady=6)
        self.chat_entry.bind("<Return>", lambda _e: self.send_message())
        if self.client is None:
            self.chat_entry.configure(
                state="disabled", placeholder_text="API key required \u2014 see Settings")
            self.send_button.configure(state="disabled", fg_color="#6B7280")

    def _available_width(self) -> int:
        try:
            self.chat_scroll.update_idletasks()
            w = self.chat_scroll.winfo_width()
            return max(w - 20, 300) if w > 1 else 800
        except Exception:
            return 800

    def _make_row(self) -> BubbleRow:
        # Remove previous bottom spacer so it stays after the last bubble
        if self._bottom_spacer is not None:
            self._bottom_spacer.destroy()
        row = BubbleRow(self.chat_scroll)
        self._bubble_rows.append(row)
        # Re-add spacer after the newest row
        self._bottom_spacer = customtkinter.CTkFrame(
            self.chat_scroll, fg_color="transparent", height=16)
        self._bottom_spacer.pack(fill="x")
        return row

    def _add_user_bubble(self, text: str, is_dark: bool) -> BubbleRow:
        row = self._make_row()
        UserBubble(row, text, is_dark=is_dark, max_width=user_width(self._available_width()))
        self._bind_mousewheel(row)
        return row

    def _add_assistant_bubble(self, is_dark: bool, md: str | None = None) -> AssistantBubble:
        row = self._make_row()
        ab = AssistantBubble(row, is_dark=is_dark, max_width=assistant_width(self._available_width()))
        if md is not None:
            ab.finalize_markdown(md)
        self._bind_mousewheel(row)
        return ab

    def _is_near_bottom(self) -> bool:
        try:
            return self.chat_scroll._parent_canvas.yview()[1] > 0.95
        except Exception:
            return True

    def _scroll_to_bottom(self) -> None:
        try:
            self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _on_resize(self, _event=None) -> None:
        avail = self._available_width()
        uw, aw = user_width(avail), assistant_width(avail)
        for row in self._bubble_rows:
            for child in row.winfo_children():
                if isinstance(child, UserBubble):
                    child.set_width(uw)
                elif isinstance(child, AssistantBubble):
                    child.set_width(aw)

    def _bind_mousewheel(self, widget) -> None:
        """Forward mousewheel/trackpad events from nested widgets to the scroll canvas."""
        try:
            canvas = self.chat_scroll._parent_canvas
        except (AttributeError, Exception):
            return
        if sys.platform == "darwin":
            widget.bind(
                "<MouseWheel>",
                lambda e: canvas.yview_scroll(int(-1 * e.delta), "units"))
        elif sys.platform == "win32":
            widget.bind(
                "<MouseWheel>",
                lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        else:
            widget.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        try:
            for child in widget.winfo_children():
                self._bind_mousewheel(child)
        except Exception:
            pass

    def send_message(self) -> None:
        """Handle the send-button / Enter-key press."""
        user_text = self.chat_entry.get().strip()
        if not user_text or (self._stream_ctrl and self._stream_ctrl.is_active):
            return
        if self._welcome_frame is not None:
            self._welcome_frame.destroy()
            self._welcome_frame = None
        self.chat_entry.delete(0, "end")
        is_dark = _is_dark_mode()
        was_near = self._is_near_bottom()
        self._add_user_bubble(user_text, is_dark)
        self._current_asst_bubble = self._add_assistant_bubble(is_dark)
        if was_near:
            self.chat_scroll.after(50, self._scroll_to_bottom)
        self.conversation_history.append({"role": "user", "content": user_text})
        self.chat_entry.configure(state="disabled")
        self.send_button.configure(state="disabled", fg_color="#6B7280")
        self._accumulated_text = ""
        self._stream_ctrl = StreamController(
            app=self.app, on_chunk=self._on_stream_chunk,
            on_done=self._on_stream_done, on_error=self._on_stream_error)
        msgs = ([{"role": "user", "content": user_text}] if self.base_url
                else list(self.conversation_history))
        extra = ({"session_id": self.session_id}
                 if self.base_url and self.session_id else None)
        self._stream_ctrl.start(
            client=self.client, model=self.model, messages=msgs,
            temperature=0.7, extra_body=extra, base_url=self.base_url)

    def _on_stream_chunk(self, chunk_text: str) -> None:
        self._accumulated_text += chunk_text
        if self._current_asst_bubble is not None:
            self._current_asst_bubble.set_streaming_text(self._accumulated_text)
        if self._is_near_bottom():
            self._scroll_to_bottom()

    def _on_stream_done(self, full_text: str) -> None:
        bubble = self._current_asst_bubble
        if bubble is not None:
            bubble.finalize_markdown(full_text)
            self._current_asst_bubble = None
        self.conversation_history.append({"role": "assistant", "content": full_text})
        self._unlock_input()
        # Delay scroll so the layout recalculates after finalize_markdown
        self.chat_scroll.after(50, self._scroll_to_bottom)
        self.chat_scroll.after(200, self._scroll_to_bottom)
        # Rebind mousewheel on new markdown widgets created by finalize
        if bubble is not None:
            self.chat_scroll.after(250, lambda: self._bind_mousewheel(bubble))

    def _on_stream_error(self, error_msg: str) -> None:
        if self._accumulated_text.strip() and self._current_asst_bubble is not None:
            self._current_asst_bubble.finalize_markdown(self._accumulated_text)
            self.conversation_history.append(
                {"role": "assistant", "content": self._accumulated_text})
            self.app.show_notification("Response may be incomplete.", type="warning")
        elif self._current_asst_bubble is not None:
            self._current_asst_bubble.set_streaming_text(f"Error: {error_msg}")
        self._current_asst_bubble = None
        self._unlock_input()

    def _unlock_input(self) -> None:
        try:
            self.chat_entry.configure(state="normal")
            self.send_button.configure(state="normal", fg_color=_RESISTINE_BLUE)
            self.chat_entry.focus_set()
        except Exception:
            pass

    def _use_suggestion(self, text: str) -> None:
        """Fill the input bar with a suggestion and send it."""
        self.chat_entry.delete(0, "end")
        self.chat_entry.insert(0, text)
        self.send_message()

    def _open_settings(self) -> None:
        """Navigate to the Settings plugin."""
        try:
            sp = next((p for p in self.app.plugin_list if p.get_name() == "Settings"), None)
            if sp:
                self.app.select_frame_by_name("frame_Settings", button=sp.get_button())
        except Exception:
            pass
