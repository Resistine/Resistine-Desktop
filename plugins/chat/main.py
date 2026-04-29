"""Resistine AI Chat plugin."""
from __future__ import annotations

import os

from plugins.base_plugin import BasePlugin
from plugins.chat.bubble import BubbleRow
from plugins.chat.chat_ui import ChatUIMixin
from plugins.chat.fonts import RESISTINE_BLUE, _is_dark_mode
from plugins.chat.history import ChatHistoryManager
from plugins.chat.streaming import StreamController
from utils import settings
from utils.logger import logger

_SYSTEM_PROMPT = "You are SOC Copilot specialized in cybersecurity."
_ICON_DIR = os.path.dirname(os.path.realpath(__file__))
_SYS_MSG = {"role": "system", "content": _SYSTEM_PROMPT}


class Plugin(ChatUIMixin, BasePlugin):
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
        self._welcome_frame: object | None = None
        self._history = ChatHistoryManager()
        self._sidebar_visible = False
        self._accumulated_text = ""
        self.reinitialize_client()
        self.status = self.get_status()
        active_id = self._history.get_active_id()
        if active_id:
            saved = self._history.load_messages(active_id)
            if saved:
                if self.base_url:
                    saved = [m for m in saved
                             if m.get("role") != "system"]
                self.conversation_history = saved

    def check_status(self):
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
            return
        try:
            kwargs: dict = {"api_key": api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            from openai import OpenAI
            self.client = OpenAI(**kwargs)
        except Exception as e:
            logger.error(f"Chat: client init failed: {e}")
            if notify:
                self.app.show_notification(
                    f"Chat Init Error: {e}", type="error")
            self.client = None

    def _save_current_session(self) -> None:
        active_id = self._history.get_active_id()
        if active_id and self.conversation_history:
            self._history.save_messages(active_id, self.conversation_history)

    def _ensure_session(self) -> None:
        if not self._history.get_active_id():
            self._history.create_session()

    def _clear_conversation(self) -> None:
        """Reset conversation and rebuild."""
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        self.conversation_history = (
            [] if self.base_url else [dict(_SYS_MSG)])
        self.session_id = None
        self._bubble_rows.clear()
        if hasattr(self, "second_frame") and self.second_frame:
            self.second_frame.destroy()
        self.create_main_screen().grid(
            row=0, column=1, sticky="nsew")

    def _new_chat(self) -> None:
        self._save_current_session()
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        self.conversation_history = (
            [] if self.base_url else [dict(_SYS_MSG)])
        self.session_id = None
        self._history.create_session()
        self._rebuild_chat()

    def _select_chat(self, session_id: str) -> None:
        if session_id == self._history.get_active_id():
            return
        self._save_current_session()
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        messages = self._history.load_messages(session_id)
        self.conversation_history = messages if messages else (
            [] if self.base_url else [dict(_SYS_MSG)])
        self._history.set_active_id(session_id)
        self._rebuild_chat()

    def _delete_chat(self, session_id: str) -> None:
        was_active = session_id == self._history.get_active_id()
        self._history.delete_session(session_id)
        if was_active:
            self.conversation_history = (
                [] if self.base_url else [dict(_SYS_MSG)])
            remaining = self._history.list_sessions()
            if remaining:
                self._select_chat(remaining[0]["id"])
                return
            self._history.create_session()
        self._rebuild_chat()

    def _rebuild_chat(self) -> None:
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        self._current_asst_bubble = None
        self._accumulated_text = ""
        self._bubble_rows.clear()
        if hasattr(self, "_chat_area") and self._chat_area:
            if hasattr(self, "chat_scroll") and self.chat_scroll:
                try:
                    self.chat_scroll.unbind("<Configure>")
                except Exception:
                    pass
            self._chat_area.destroy()
        self._chat_area = self.chat_scroll = self.chat_entry = None
        self.send_button = self._bottom_spacer = None
        self._build_chat_area(_is_dark_mode())
        self._refresh_sidebar()

    def send_message(self) -> None:
        user_text = self.chat_entry.get().strip()
        if not user_text:
            return
        if len(user_text) > 15000:
            self.app.show_notification(
                "Message too long (15,000 character limit).",
                type="warning")
            return
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stop_streaming()
            return
        self._ensure_session()
        if self._welcome_frame is not None:
            self._welcome_frame.destroy()
            self._welcome_frame = None
        self._show_header()
        self.chat_entry.delete(0, "end")
        is_dark = _is_dark_mode()
        was_near = self._is_near_bottom()
        self._add_user_bubble(user_text, is_dark)
        self._current_asst_bubble = self._add_assistant_bubble(is_dark)
        self.chat_scroll.after(50, self._scroll_to_last_user_bubble)
        self.chat_scroll.after(100, self._update_scrollbar_visibility)
        self.conversation_history.append(
            {"role": "user", "content": user_text})
        self.chat_entry.configure(state="disabled")
        self.send_button.configure(
            text="\u25a0", fg_color="#EF4444", hover_color="#DC2626",
            command=self._stop_streaming)
        self._accumulated_text = ""
        self._stream_ctrl = StreamController(
            app=self.app, on_chunk=self._on_stream_chunk,
            on_done=self._on_stream_done, on_error=self._on_stream_error)
        msgs = ([{"role": "user", "content": user_text}]
                if self.base_url
                else list(self.conversation_history))
        extra = ({"session_id": self.session_id}
                 if self.base_url and self.session_id else None)
        self._stream_ctrl.start(
            client=self.client, model=self.model, messages=msgs,
            temperature=0.7, extra_body=extra, base_url=self.base_url)

    def _stop_streaming(self) -> None:
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        if (self._accumulated_text.strip()
                and self._current_asst_bubble):
            self._current_asst_bubble.finalize_markdown(
                self._accumulated_text)
            self.conversation_history.append(
                {"role": "assistant", "content": self._accumulated_text})
        elif self._current_asst_bubble:
            self._current_asst_bubble._stop_thinking()
            self._current_asst_bubble.destroy()
        self._current_asst_bubble = None
        self._unlock_input()
        self._save_current_session()
        self._refresh_sidebar()

    def _on_stream_chunk(self, chunk_text: str) -> None:
        self._accumulated_text += chunk_text
        if self._current_asst_bubble is not None:
            self._current_asst_bubble.set_streaming_text(
                self._accumulated_text)
        if self._is_near_bottom():
            self._scroll_to_bottom()
        self._check_scroll_btn()

    def _on_stream_done(self, full_text: str) -> None:
        if self._current_asst_bubble is not None:
            self._current_asst_bubble.finalize_markdown(full_text)
            self._current_asst_bubble = None
            self.conversation_history.append(
                {"role": "assistant", "content": full_text})
        self._unlock_input()
        self._save_current_session()
        self._refresh_sidebar()
        self.chat_scroll.after(50, self._scroll_to_last_user_bubble)
        self.chat_scroll.after(200, self._scroll_to_last_user_bubble)
        self.chat_scroll.after(250, self._update_scrollbar_visibility)

    def _on_stream_error(self, error_msg: str) -> None:
        if (self._accumulated_text.strip()
                and self._current_asst_bubble is not None):
            self._current_asst_bubble.finalize_markdown(
                self._accumulated_text)
            self.conversation_history.append(
                {"role": "assistant", "content": self._accumulated_text})
            self.app.show_notification(
                "Response may be incomplete.", type="warning")
        elif self._current_asst_bubble is not None:
            try:
                self._current_asst_bubble.set_streaming_text(
                    f"Error: {error_msg}")
            except Exception:
                pass
        self._current_asst_bubble = None
        self._unlock_input()
        self._save_current_session()

    def _unlock_input(self) -> None:
        try:
            self.chat_entry.configure(state="normal")
            self.send_button.configure(
                text="\u2191", state="normal",
                fg_color=RESISTINE_BLUE,
                hover_color="#1565B0",
                command=self.send_message)
            self.chat_entry.focus_set()
        except Exception:
            pass

    def _use_suggestion(self, text: str) -> None:
        self.chat_entry.delete(0, "end")
        self.chat_entry.insert(0, text)
        self.send_message()

    def _open_settings(self) -> None:
        try:
            sp = next((p for p in self.app.plugin_list if p.get_name() == "Settings"), None)
            if sp:
                self.app.select_frame_by_name("frame_Settings", button=sp.get_button())
        except Exception:
            pass
