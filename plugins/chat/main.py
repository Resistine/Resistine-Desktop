"""Resistine AI Chat plugin."""
from __future__ import annotations

import os

import customtkinter

from plugins.base_plugin import BasePlugin
from plugins.chat.bubble import (
    AssistantBubble, BubbleRow, UserBubble, assistant_width, user_width,
)
from plugins.chat.fonts import _is_dark_mode
from plugins.chat.history import ChatHistoryManager
from plugins.chat.sidebar import ChatSidebar
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
        self._history = ChatHistoryManager()
        self._sidebar_visible = True
        self.reinitialize_client()
        self.status = self.get_status()
        # Restore active session
        active_id = self._history.get_active_id()
        if active_id:
            saved = self._history.load_messages(active_id)
            if saved:
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
        self.conversation_history.append(
            {"role": "user", "content": message})
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
                model=self.model,
                messages=self.conversation_history, stream=True)
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                full += chunk.choices[0].delta.content
                yield chunk.choices[0].delta.content
            if self.base_url and hasattr(chunk, "session_id"):
                self.session_id = chunk.session_id
        self.conversation_history.append(
            {"role": "assistant", "content": full})

    # -- Session management ------------------------------------------------

    def _save_current_session(self) -> None:
        active_id = self._history.get_active_id()
        if active_id and self.conversation_history:
            self._history.save_messages(active_id, self.conversation_history)

    def _ensure_session(self) -> None:
        if not self._history.get_active_id():
            self._history.create_session()

    def _clear_conversation(self) -> None:
        """Reset conversation and rebuild. Alias kept for compatibility."""
        self.conversation_history = [] if self.base_url else [dict(_SYS_MSG)]
        self.session_id = None
        self._bubble_rows.clear()
        if hasattr(self, "second_frame") and self.second_frame:
            self.second_frame.destroy()
        self.create_main_screen().grid(row=0, column=1, sticky="nsew")

    def _new_chat(self) -> None:
        self._save_current_session()
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        self.conversation_history = [] if self.base_url else [dict(_SYS_MSG)]
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
            self.conversation_history = [] if self.base_url else [dict(_SYS_MSG)]
            remaining = self._history.list_sessions()
            if remaining:
                self._select_chat(remaining[0]["id"])
                return
            self._history.create_session()
        self._rebuild_chat()

    def _rebuild_chat(self) -> None:
        self._bubble_rows.clear()
        if hasattr(self, "_chat_area") and self._chat_area:
            if hasattr(self, "chat_scroll") and self.chat_scroll:
                try:
                    self.chat_scroll.unbind("<Configure>")
                except Exception:
                    pass
            self._chat_area.destroy()
        # Clear widget references to avoid dangling pointers
        self._chat_area = None
        self.chat_scroll = None
        self.chat_entry = None
        self.send_button = None
        self._current_asst_bubble = None
        self._build_chat_area(_is_dark_mode())
        self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        if hasattr(self, "_sidebar") and self._sidebar:
            self._sidebar.refresh(
                self._history.list_sessions(),
                self._history.get_active_id())

    # -- UI construction ---------------------------------------------------

    def create_main_screen(self):
        is_dark = _is_dark_mode()
        self._ensure_session()

        self.second_frame = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent")

        # Sidebar
        self._sidebar = ChatSidebar(
            self.second_frame,
            on_select=self._select_chat,
            on_new_chat=self._new_chat,
            on_delete=self._delete_chat,
            is_dark=is_dark)
        if self._sidebar_visible:
            self._sidebar.pack(side="left", fill="y")
        # If _sidebar_visible is False, don't pack (user toggled it off)

        self._build_chat_area(is_dark)
        self._refresh_sidebar()
        return self.second_frame

    def _build_chat_area(self, is_dark: bool) -> None:
        self._chat_area = customtkinter.CTkFrame(
            self.second_frame, corner_radius=0, fg_color="transparent")
        self._chat_area.pack(side="left", fill="both", expand=True)
        self._chat_area.grid_columnconfigure(0, weight=1)
        self._chat_area.grid_rowconfigure(0, weight=1)

        self.chat_scroll = customtkinter.CTkScrollableFrame(
            self._chat_area, fg_color="transparent", corner_radius=0)
        self.chat_scroll.grid(
            row=0, column=0, padx=0, pady=(0, 62), sticky="nsew")

        self._bubble_rows.clear()
        self._welcome_frame = None
        self._bottom_spacer: customtkinter.CTkFrame | None = None
        self._current_asst_bubble: AssistantBubble | None = None
        self._restore_history(is_dark)
        self._build_input_bar(is_dark)
        self._build_overlay_buttons(is_dark)
        self.chat_scroll.bind("<Configure>", self._on_resize, add="+")
        # Detect scroll for scroll-to-bottom button
        try:
            canvas = self.chat_scroll._parent_canvas
            canvas.bind(
                "<MouseWheel>",
                lambda _e: self.chat_scroll.after(
                    100, self._check_scroll_btn),
                add="+")
        except Exception:
            pass

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
            self._chat_area, fg_color=bg,
            corner_radius=22, border_width=1, border_color=brd)
        bar.place(relx=0.5, rely=1.0, anchor="s", relwidth=0.98, y=-14)
        bar.grid_columnconfigure(0, weight=1)
        self.chat_entry = EmojiEntry(
            bar, placeholder_text="Message Resistine AI...",
            corner_radius=20, border_width=0, height=44,
            font=customtkinter.CTkFont(family="Inter", size=14),
            fg_color="transparent", text_color=fg,
            placeholder_text_color="#8ea8c6" if is_dark else "#9aa5b1")
        self.chat_entry.grid(
            row=0, column=0, padx=(16, 4), pady=0, sticky="ew")
        self.send_button = customtkinter.CTkButton(
            bar, text="\u2191", command=self.send_message,
            corner_radius=18, height=36, width=36,
            font=customtkinter.CTkFont(size=18, weight="bold"),
            fg_color=_RESISTINE_BLUE, hover_color="#1565B0",
            text_color="#ffffff")
        self.send_button.grid(row=0, column=1, padx=(0, 6), pady=6)
        self.chat_entry.bind("<Return>", lambda _e: self.send_message())
        if self.client is None:
            self.chat_entry.configure(
                state="disabled",
                placeholder_text="API key required \u2014 see Settings")
            self.send_button.configure(state="disabled", fg_color="#6B7280")

    def _build_overlay_buttons(self, is_dark: bool) -> None:
        fg = "#e0e0e0" if is_dark else "#1a1a1a"
        btn_bg = "#2A2A2C" if is_dark else "#E8E8EA"
        hover_bg = "#3A3A3C" if is_dark else "#D8D8DC"

        self._toggle_btn = customtkinter.CTkButton(
            self._chat_area, text="\u2630", width=34, height=34,
            corner_radius=9, fg_color=btn_bg, hover_color=hover_bg,
            text_color=fg,
            font=customtkinter.CTkFont(size=16),
            command=self._toggle_sidebar)
        self._toggle_btn.place(x=12, y=8)

        self._scroll_btn = customtkinter.CTkButton(
            self._chat_area, text="\u25BC", width=30, height=30,
            corner_radius=15,
            fg_color=_RESISTINE_BLUE, hover_color="#1565B0",
            text_color="#ffffff",
            font=customtkinter.CTkFont(size=10),
            command=self._scroll_to_bottom)
        self._scroll_btn_visible = False

    def _toggle_sidebar(self) -> None:
        if self._sidebar_visible:
            self._sidebar.pack_forget()
        else:
            self._sidebar.pack(side="left", fill="y",
                               before=self._chat_area)
        self._sidebar_visible = not self._sidebar_visible

    def _check_scroll_btn(self) -> None:
        if not hasattr(self, "_scroll_btn") or self._scroll_btn is None:
            return
        near = self._is_near_bottom()
        if not near and not self._scroll_btn_visible:
            try:
                self._scroll_btn.place(relx=0.5, rely=1.0, anchor="s", y=-72)
                self._scroll_btn_visible = True
            except Exception:
                pass
        elif near and self._scroll_btn_visible:
            try:
                self._scroll_btn.place_forget()
            except Exception:
                pass
            self._scroll_btn_visible = False

    # -- Bubble helpers ----------------------------------------------------

    def _available_width(self) -> int:
        try:
            self.chat_scroll.update_idletasks()
            w = self.chat_scroll.winfo_width()
            return max(w - 20, 300) if w > 1 else 800
        except Exception:
            return 800

    def _make_row(self) -> BubbleRow:
        if self._bottom_spacer is not None:
            self._bottom_spacer.destroy()
        row = BubbleRow(self.chat_scroll)
        self._bubble_rows.append(row)
        self._bottom_spacer = customtkinter.CTkFrame(
            self.chat_scroll, fg_color="transparent", height=16)
        self._bottom_spacer.pack(fill="x")
        return row

    def _add_user_bubble(self, text: str, is_dark: bool) -> BubbleRow:
        row = self._make_row()
        UserBubble(row, text, is_dark=is_dark,
                   max_width=user_width(self._available_width()))
        return row

    def _add_assistant_bubble(
        self, is_dark: bool, md: str | None = None,
    ) -> AssistantBubble:
        row = self._make_row()
        ab = AssistantBubble(
            row, is_dark=is_dark,
            max_width=assistant_width(self._available_width()))
        if md is not None:
            ab.finalize_markdown(md)
        return ab

    def _is_near_bottom(self) -> bool:
        try:
            if self.chat_scroll is None:
                return True
            return self.chat_scroll._parent_canvas.yview()[1] > 0.95
        except Exception:
            return True

    def _scroll_to_bottom(self) -> None:
        try:
            if self.chat_scroll is not None:
                self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass
        if hasattr(self, "_scroll_btn") and self._scroll_btn_visible:
            try:
                self._scroll_btn.place_forget()
            except Exception:
                pass
            self._scroll_btn_visible = False

    def _on_resize(self, _event=None) -> None:
        avail = self._available_width()
        uw, aw = user_width(avail), assistant_width(avail)
        for row in self._bubble_rows:
            for child in row.winfo_children():
                if isinstance(child, UserBubble):
                    child.set_width(uw)
                elif isinstance(child, AssistantBubble):
                    child.set_width(aw)
        self._check_scroll_btn()

    # -- Sending & streaming -----------------------------------------------

    def send_message(self) -> None:
        user_text = self.chat_entry.get().strip()
        if not user_text:
            return
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stop_streaming()
            return
        self._ensure_session()
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
        self.conversation_history.append(
            {"role": "user", "content": user_text})
        # Swap to stop button
        self.chat_entry.configure(state="disabled")
        self.send_button.configure(
            text="\u25A0", fg_color="#EF4444", hover_color="#DC2626",
            command=self._stop_streaming)
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

    def _stop_streaming(self) -> None:
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        if self._accumulated_text.strip() and self._current_asst_bubble:
            self._current_asst_bubble.finalize_markdown(
                self._accumulated_text)
            self.conversation_history.append(
                {"role": "assistant", "content": self._accumulated_text})
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
        self.chat_scroll.after(50, self._scroll_to_bottom)
        self.chat_scroll.after(200, self._scroll_to_bottom)

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
                text="\u2191", state="normal", fg_color=_RESISTINE_BLUE,
                hover_color="#1565B0", command=self.send_message)
            self.chat_entry.focus_set()
        except Exception:
            pass

    def _use_suggestion(self, text: str) -> None:
        self.chat_entry.delete(0, "end")
        self.chat_entry.insert(0, text)
        self.send_message()

    def _open_settings(self) -> None:
        try:
            sp = next(
                (p for p in self.app.plugin_list
                 if p.get_name() == "Settings"), None)
            if sp:
                self.app.select_frame_by_name(
                    "frame_Settings", button=sp.get_button())
        except Exception:
            pass
