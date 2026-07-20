"""Resistine AI Chat plugin (PyQt6).

Faithful PyQt6 port of the original CustomTkinter chat screen. Reproduces the
same regions 1:1:

  * Top bar  -- hamburger menu toggle (left), "Resistine AI" title (centre),
                "+" New Chat button (right).
  * History drawer -- a collapsible left panel listing saved sessions with
                select + delete, slid open/closed by the hamburger, dimming the
                chat behind it.
  * Message area -- a vertically scrolling list of user bubbles (right-aligned,
                blue) and assistant bubbles (left-aligned, rendered as MARKDOWN
                via Qt's MarkdownText format).
  * Welcome screen -- centred greeting + "TRY ASKING" suggestion chips when the
                conversation is empty (or an "API key required" panel when no
                client is configured).
  * Input bar -- rounded entry "Message Resistine AI..." + a send button that
                shows "↑" and toggles to a red "■" stop glyph while streaming.

The streaming controller, history manager and markdown utilities are reused
verbatim from the framework-agnostic backend modules.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""
from __future__ import annotations

import os
import random

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QStyle,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from plugins.base_plugin import BasePlugin
from plugins.chat.history import ChatHistoryManager
from plugins.chat.streaming import StreamController
from plugins.chat.suggestions import SUGGESTION_POOL
from utils import settings
from utils.logger import logger

# Appended to history when the user navigates away mid-response: the partial
# text is discarded and this canned marker is stored instead.
_NAV_AWAY_MSG = (
    "_(You switched chats before this response could finish. "
    "Please ask your question again.)_"
)

_SYSTEM_PROMPT = "You are SOC Copilot specialized in cybersecurity."
_ICON_DIR = os.path.dirname(os.path.realpath(__file__))
_SYS_MSG = {"role": "system", "content": _SYSTEM_PROMPT}
_DEFAULT_BASE_URL = "https://dashboard.resisti.net:8002/v1"


def _tls_verify() -> str | bool:
    """httpx ``verify`` value for the HTTPS chat endpoint.

    The dashboard serves a leaf-only certificate (no intermediate) signed
    by the internal Resistine root CA, so the default certifi store cannot
    validate it. Resolution order: RESISTINE_CA_BUNDLE env var, a
    ``certs/resistine-rootCA.pem`` override in the config dir, then the
    root CA bundled with the app. If all are missing (shouldn't happen --
    the bundled cert ships in resources/), fall back to standard
    verification rather than disabling it.
    """
    ca = os.environ.get("RESISTINE_CA_BUNDLE")
    if ca and os.path.isfile(ca):
        return ca
    ca = os.path.join(
        settings.get_config_dir(), "certs", "resistine-rootCA.pem")
    if os.path.isfile(ca):
        return ca
    from utils.functions import get_resource_path
    ca = get_resource_path(
        os.path.join("resources", "certs", "resistine-rootCA.pem"))
    if os.path.isfile(ca):
        return ca
    return True

RESISTINE_BLUE = "#0D5394"
_ACCENT_HOVER = "#1565B0"
_STOP_RED = "#EF4444"
_STOP_RED_HOVER = "#DC2626"

# Bubble width caps (mirror plugins/chat/bubble.py).
# Width ceilings for bubbles. The effective width is dynamic — a fraction of
# the visible chat area, clamped to these caps (see _apply_bubble_widths) —
# so bubbles use the room they're given instead of wrapping at a fixed 480px.
_ASST_MAX = 860
_USER_MAX = 720
_BUBBLE_FRACTION = 0.78  # of the message-area viewport width

_SIDEBAR_WIDTH = 240


# ---------------------------------------------------------------------------
# Bubble widgets
# ---------------------------------------------------------------------------

class _Bubble(QFrame):
    """A single chat bubble — a rounded QLabel-bearing frame in a flow row."""

    def __init__(self, *, is_user: bool, max_width: int):
        super().__init__()
        self._is_user = is_user
        self.setSizePolicy(QSizePolicy.Policy.Maximum,
                           QSizePolicy.Policy.Preferred)

        if is_user:
            bg = theme.color("bubble_user_bg")
            fg = theme.color("bubble_user_text")
            border = bg
        else:
            bg = theme.color("bubble_ai_bg")
            fg = theme.color("bubble_ai_text")
            border = theme.color("border")

        self.setStyleSheet(
            f"#ChatBubble {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 16px; }}")
        self.setObjectName("ChatBubble")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(0)

        self._label = QLabel()
        self._label.setObjectName("ChatBubbleText")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setStyleSheet(
            f"#ChatBubbleText {{ background: transparent; border: none; "
            f"color: {fg}; font-size: 14px; }}")
        if is_user:
            self._label.setTextFormat(Qt.TextFormat.PlainText)
        else:
            self._label.setTextFormat(Qt.TextFormat.MarkdownText)
        self._label.setMaximumWidth(max_width)
        lay.addWidget(self._label)

        # Thinking placeholder (assistant only) until first chunk arrives.
        if not is_user:
            self._label.setText("…")
        self._max_width = max_width

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def set_max_width(self, max_width: int) -> None:
        self._max_width = max_width
        self._label.setMaximumWidth(max_width)


class _BubbleRow(QWidget):
    """Full-width row holding one bubble, aligned left or right."""

    def __init__(self, bubble: _Bubble, *, is_user: bool):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(0)
        if is_user:
            lay.addStretch(1)
            lay.addWidget(bubble)
        else:
            lay.addWidget(bubble)
            lay.addStretch(1)
        self.bubble = bubble


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class Plugin(BasePlugin):
    """Chat plugin -- lets users talk to an OpenAI-compatible AI assistant."""

    defer_reveal_until_settled = True

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
        self._stream_ctrl: StreamController | None = None
        self._history = ChatHistoryManager()
        # One-shot cleanup: removes "New Chat"-titled empty sessions left
        # over from previous runs.
        try:
            self._history.cleanup_empty()
        except Exception:
            pass
        self._sidebar_visible = False
        self._accumulated_text = ""
        self._response_persisted = False
        self._gate_timer = None
        self._current_asst_bubble: _Bubble | None = None
        self._welcome_widget: QWidget | None = None
        self.reinitialize_client()
        self.status = self.get_status()
        active_id = self._history.get_active_id()
        if active_id:
            saved = self._history.load_messages(active_id)
            if saved:
                if self.base_url:
                    saved = [m for m in saved if m.get("role") != "system"]
                self.conversation_history = saved

    # ===================================================================
    #  Status / client
    # ===================================================================
    def check_status(self):
        if not self.client:
            return "Warning"
        # Access gate: chat is only usable when VPN + agent are both active.
        vpn_on, agent_on = self._chat_access_status()
        return "OK" if (vpn_on and agent_on) else "Warning"

    @staticmethod
    def _chat_access_status() -> tuple[bool, bool]:
        """Return (vpn_connected, endpoint_agent_running) for the gate.

        The agent check is "running" (not merely "installed") so that
        manually toggling the SIEM agent off re-locks chat.
        """
        vpn_on = False
        try:
            from plugins.vpn.main import is_vpn_connected
            vpn_on = bool(is_vpn_connected())
        except Exception:
            vpn_on = False
        agent_on = False
        try:
            from plugins.wazuh.main import is_agent_running
            agent_on = bool(is_agent_running())
        except Exception:
            agent_on = False
        return vpn_on, agent_on

    def reinitialize_client(self, notify: bool = False):
        """Rebuild the OpenAI client from the current settings."""
        api_key = settings.get_secret("chat", "openai_api_key")
        self.base_url = (
            settings.get("chat", "openai_base_url") or _DEFAULT_BASE_URL)
        self.session_id = None
        if self.base_url:
            self.model, self.conversation_history = "ministral-3:14b", []
        else:
            self.model = "gpt-4o"
            self.conversation_history = [dict(_SYS_MSG)]
        if not api_key and not self.base_url:
            self.client = None
            return
        try:
            kwargs: dict = {"api_key": api_key or "unused"}
            if self.base_url:
                kwargs["base_url"] = self.base_url
                if self.base_url.lower().startswith("https://"):
                    # Internal root CA for the HTTPS dashboard endpoint.
                    import httpx
                    kwargs["http_client"] = httpx.Client(
                        verify=_tls_verify())
            from openai import OpenAI
            self.client = OpenAI(**kwargs)
        except Exception as e:
            logger.error(f"Chat: client init failed: {e}")
            if notify:
                try:
                    self.app.show_notification(
                        f"Chat Init Error: {e}", type="error")
                except Exception:
                    pass
            self.client = None
        # Reflect any client change in a live screen's input controls.
        try:
            self._sync_input_enabled()
        except Exception:
            pass

    # ===================================================================
    #  Screen construction
    # ===================================================================
    def create_main_screen(self):
        # Access gate: chat is only available when the VPN is connected AND
        # the SIEM/Endpoint agent is RUNNING. A QTimer poller re-checks while
        # the screen is alive, so toggling the agent off or dropping the VPN
        # snaps chat back to the locked screen — and turning them back on
        # unlocks it — without navigating away and back.
        vpn_on, agent_on = self._chat_access_status()
        self._gate_unlocked = bool(vpn_on and agent_on)
        if not self._gate_unlocked:
            locked = self._build_locked_screen(vpn_on, agent_on)
            self._start_gate_poller(locked)
            self.second_frame = locked
            return locked

        self._ensure_session()

        root = QWidget()
        root.setObjectName("ChatRoot")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # -- History drawer (collapsible left panel) --
        self._sidebar = self._build_sidebar()
        self._sidebar.setVisible(self._sidebar_visible)
        outer.addWidget(self._sidebar)

        # -- Chat column (top bar + messages + input) --
        chat_col = QWidget()
        col = QVBoxLayout(chat_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(self._build_top_bar())
        col.addWidget(self._build_message_area(), 1)
        col.addWidget(self._build_input_bar())

        outer.addWidget(chat_col, 1)

        self.second_frame = root
        self._restore_history()
        self._refresh_sidebar()
        self._sync_input_enabled()
        self._start_gate_poller(root)
        return root

    # ---- Access gate -------------------------------------------------------
    def _start_gate_poller(self, owner: QWidget) -> None:
        """Re-check the VPN+agent gate every few seconds while chat is shown.

        The QTimer is parented to the screen widget, so it stops and is
        destroyed with the screen — no manual teardown needed.
        """
        timer = QTimer(owner)
        timer.setInterval(4000)

        def _tick():
            vpn_on, agent_on = self._chat_access_status()
            unlocked = bool(vpn_on and agent_on)
            if unlocked == self._gate_unlocked:
                return
            timer.stop()
            if not unlocked:
                # Re-locking mid-stream: persist what we can first.
                try:
                    self._finalize_in_flight_response(persist=True)
                except Exception:
                    pass
            try:
                self.status = self.check_status()
                self.app.update_plugin(self.id)
            except Exception:
                logger.debug("Chat: gate refresh failed")

        timer.timeout.connect(_tick)
        timer.start()
        self._gate_timer = timer

    def _build_locked_screen(self, vpn_on: bool, agent_on: bool) -> QWidget:
        """Referral screen shown while the access gate is locked."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch(1)

        title = QLabel("Resistine AI is locked")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 700; "
            f"color: {theme.color('text_primary')};")
        lay.addWidget(title)
        lay.addSpacing(8)

        sub = QLabel(
            "Chat is available when your connection is protected.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(
            f"font-size: 14px; color: {theme.color('text_secondary')};")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(16)

        for ok, txt in (
            (vpn_on, "VPN connected"),
            (agent_on, "Endpoint agent running"),
        ):
            row = QLabel(("✓  " if ok else "✗  ") + txt)
            row.setAlignment(Qt.AlignmentFlag.AlignCenter)
            color = "#1E8E3E" if ok else "#C5221F"
            row.setStyleSheet(f"font-size: 14px; color: {color};")
            lay.addWidget(row)

        lay.addSpacing(16)
        hint = QLabel(
            "Connect the VPN and start the Endpoint agent to unlock chat. "
            "This screen unlocks automatically.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 12px; color: {theme.color('text_secondary')};")
        lay.addWidget(hint)
        lay.addStretch(1)
        return page

    # ---- Top bar ----------------------------------------------------------
    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        self._toggle_btn = self._icon_button("☰")  # hamburger
        self._toggle_btn.clicked.connect(self._toggle_sidebar)
        lay.addWidget(self._toggle_btn)

        lay.addStretch(1)
        title = QLabel("Resistine AI")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; "
            f"color: {theme.color('text_primary')}; background: transparent;")
        lay.addWidget(title)
        lay.addStretch(1)

        self._new_chat_btn = self._icon_button("+")
        self._new_chat_btn.clicked.connect(self._new_chat)
        lay.addWidget(self._new_chat_btn)
        return bar

    def _icon_button(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("Secondary")
        btn.setFixedSize(32, 32)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            "QPushButton { font-size: 18px; font-weight: 700; padding: 0; "
            "border-radius: 8px; }")
        return btn

    # ---- Message area -----------------------------------------------------
    def _build_message_area(self) -> QWidget:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._messages = QWidget()
        self._messages_lay = QVBoxLayout(self._messages)
        self._messages_lay.setContentsMargins(0, 8, 0, 8)
        self._messages_lay.setSpacing(2)
        self._messages_lay.addStretch(1)  # bottom spacer keeps rows top-packed
        self._scroll.setWidget(self._messages)
        # Re-fit every bubble's max width when the chat area resizes.
        _orig_resize = self._scroll.resizeEvent

        def _on_scroll_resize(event, _orig=_orig_resize):
            _orig(event)
            self._apply_bubble_widths()

        self._scroll.resizeEvent = _on_scroll_resize
        return self._scroll

    def _bubble_widths(self) -> tuple[int, int]:
        """(user, assistant) max widths for the current viewport size."""
        try:
            avail = self._scroll.viewport().width() - 24  # row margins
        except Exception:
            avail = 0
        if avail <= 0:
            return _USER_MAX, _ASST_MAX
        dyn = int(avail * _BUBBLE_FRACTION)
        return min(_USER_MAX, dyn), min(_ASST_MAX, dyn)

    def _apply_bubble_widths(self) -> None:
        user_w, asst_w = self._bubble_widths()
        lay = getattr(self, "_messages_lay", None)
        if lay is None:
            return
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            bubble = getattr(w, "bubble", None)
            if bubble is not None:
                bubble.set_max_width(
                    user_w if bubble._is_user else asst_w)

    # ---- Input bar --------------------------------------------------------
    def _build_input_bar(self) -> QWidget:
        wrap = QFrame()
        wrap.setStyleSheet("background: transparent;")
        outer = QHBoxLayout(wrap)
        outer.setContentsMargins(16, 8, 16, 14)
        outer.setSpacing(0)
        outer.addStretch(1)

        bar = QFrame()
        bar.setObjectName("ChatInputBar")
        bar.setMaximumWidth(900)
        bg = theme.color("input_bg")
        brd = theme.color("border")
        bar.setStyleSheet(
            f"#ChatInputBar {{ background-color: {bg}; border: 1px solid {brd}; "
            f"border-radius: 22px; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.chat_entry = QLineEdit()
        self.chat_entry.setPlaceholderText("Message Resistine AI...")
        self.chat_entry.setStyleSheet(
            "QLineEdit { background: transparent; border: none; "
            "font-size: 15px; padding: 6px 10px; }")
        self.chat_entry.returnPressed.connect(self.send_message)
        row.addWidget(self.chat_entry, 1)

        self.send_button = QPushButton("↑")
        self.send_button.setFixedSize(36, 36)
        self.send_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._style_send_button(stop=False)
        self.send_button.clicked.connect(self.send_message)
        row.addWidget(self.send_button)

        outer.addWidget(bar, 6)
        outer.addStretch(1)
        return wrap

    def _style_send_button(self, *, stop: bool) -> None:
        if stop:
            bg, hover, text = _STOP_RED, _STOP_RED_HOVER, "■"
        else:
            bg, hover, text = RESISTINE_BLUE, _ACCENT_HOVER, "↑"
        self.send_button.setText(text)
        self.send_button.setStyleSheet(
            f"QPushButton {{ background-color: {bg}; color: #ffffff; "
            f"border: none; border-radius: 18px; font-size: 17px; "
            f"font-weight: 700; padding: 0; }}"
            f"QPushButton:hover {{ background-color: {hover}; }}"
            f"QPushButton:disabled {{ background-color: #6B7280; }}")

    # ---- History drawer ---------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("ChatSidebar")
        panel.setFixedWidth(_SIDEBAR_WIDTH)
        bg = theme.color("sidebar_bg")
        brd = theme.color("divider")
        panel.setStyleSheet(
            f"#ChatSidebar {{ background-color: {bg}; "
            f"border-right: 1px solid {brd}; }}")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 10, 8, 8)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(4, 0, 0, 0)
        title = QLabel("HISTORY")
        title.setStyleSheet(
            "font-size: 10px; font-weight: 700; color: #6B7280; "
            "background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch(1)
        new_btn = QPushButton("+ New")
        new_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        new_btn.setStyleSheet(
            f"QPushButton {{ background-color: {RESISTINE_BLUE}; color: #fff; "
            f"border: none; border-radius: 7px; padding: 5px 10px; "
            f"font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}")
        new_btn.clicked.connect(self._new_chat)
        hdr.addWidget(new_btn)
        lay.addLayout(hdr)

        self._sidebar_scroll = QScrollArea()
        self._sidebar_scroll.setWidgetResizable(True)
        self._sidebar_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._sidebar_scroll.setStyleSheet("background: transparent;")
        self._sidebar_list = QWidget()
        self._sidebar_list_lay = QVBoxLayout(self._sidebar_list)
        self._sidebar_list_lay.setContentsMargins(0, 0, 0, 0)
        self._sidebar_list_lay.setSpacing(2)
        self._sidebar_list_lay.addStretch(1)
        self._sidebar_scroll.setWidget(self._sidebar_list)
        lay.addWidget(self._sidebar_scroll, 1)
        return panel

    def _refresh_sidebar(self) -> None:
        lay = getattr(self, "_sidebar_list_lay", None)
        if lay is None:
            return
        # Clear existing items (keep the trailing stretch).
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        sessions = self._history.list_sessions()
        active_id = self._history.get_active_id()
        if not sessions:
            empty = QLabel("No conversations")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(
                "color: #6B7280; font-size: 12px; background: transparent;")
            lay.insertWidget(0, empty)
            return
        for s in sessions:
            lay.insertWidget(
                lay.count() - 1,
                self._sidebar_item(
                    s["id"], s.get("title", "New Chat"),
                    s["id"] == active_id))

    def _sidebar_item(self, sid: str, title: str, active: bool) -> QWidget:
        is_dark = theme.is_dark()
        active_bg = "#1A2F45" if is_dark else "#D6E4F0"
        fg = theme.color("text_primary")
        row = QFrame()
        row.setObjectName("ChatHistoryItem")
        bgrule = f"background-color: {active_bg};" if active else ""
        row.setStyleSheet(
            f"#ChatHistoryItem {{ {bgrule} border-radius: 8px; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 4, 4, 4)
        rl.setSpacing(2)

        lbl = QLabel()
        # Set the font on the WIDGET (not via QSS): elidedText() must use the
        # same metrics the label paints with — the stylesheet font-size isn't
        # reflected in fontMetrics(), which made the elided string ~10px too
        # wide and pushed the delete ✕ past the drawer edge.
        _f = lbl.font()
        _f.setPixelSize(12)
        lbl.setFont(_f)
        lbl.setStyleSheet(f"color: {fg}; background: transparent;")
        # Generous slack: drawer margins + row margins + spacing + the ✕.
        avail = _SIDEBAR_WIDTH - 80
        lbl.setText(lbl.fontMetrics().elidedText(
            title, Qt.TextElideMode.ElideRight, avail))
        lbl.setMaximumWidth(avail)  # hard cap — the ✕ always fits
        lbl.setToolTip(title)
        lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        lbl.mousePressEvent = lambda _e, s=sid: self._select_chat(s)
        rl.addWidget(lbl, 1)

        # Standard close icon from the platform style, NOT a "✕" text glyph —
        # the glyph rendered blank (missing from the active font), which made
        # the delete affordance invisible even though the button was there.
        del_btn = QPushButton()
        del_btn.setIcon(row.style().standardIcon(
            QStyle.StandardPixmap.SP_TitleBarCloseButton))
        del_btn.setIconSize(QSize(12, 12))
        del_btn.setFixedSize(24, 24)
        del_btn.setToolTip("Delete chat")
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "border-radius: 6px; }"
            f"QPushButton:hover {{ background: "
            f"{theme.color('sidebar_hover_bg')}; }}")
        del_btn.clicked.connect(lambda _=False, s=sid: self._delete_chat(s))
        rl.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        if getattr(self, "_sidebar", None) is not None:
            self._sidebar.setVisible(self._sidebar_visible)

    # ===================================================================
    #  Welcome screen
    # ===================================================================
    def _restore_history(self) -> None:
        has_history = False
        for msg in self.conversation_history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                continue
            has_history = True
            if role == "user":
                self._add_user_bubble(content)
            elif role == "assistant":
                self._add_assistant_bubble(md=content)
        if has_history:
            return
        if self.client is not None:
            self._welcome_widget = self._build_welcome_screen()
        else:
            self._welcome_widget = self._build_api_missing_screen()
        self._messages_lay.insertWidget(
            self._messages_lay.count() - 1, self._welcome_widget,
            0, Qt.AlignmentFlag.AlignCenter)

    def _clear_welcome(self) -> None:
        if self._welcome_widget is not None:
            self._welcome_widget.setParent(None)
            self._welcome_widget.deleteLater()
            self._welcome_widget = None

    def _build_welcome_screen(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        greeting = QLabel("How can I help you today?")
        greeting.setAlignment(Qt.AlignmentFlag.AlignCenter)
        greeting.setStyleSheet(
            f"font-size: 24px; font-weight: 700; "
            f"color: {theme.color('text_primary')}; background: transparent;")
        lay.addWidget(greeting)

        subtitle = QLabel("Ask me anything about cybersecurity")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"font-size: 14px; color: {theme.color('text_secondary')}; "
            f"background: transparent;")
        lay.addWidget(subtitle)
        lay.addSpacing(14)

        section = QLabel("TRY ASKING")
        section.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {RESISTINE_BLUE}; "
            f"background: transparent;")
        lay.addWidget(section)
        lay.addSpacing(8)

        for suggestion in random.sample(
                SUGGESTION_POOL, min(4, len(SUGGESTION_POOL))):
            lay.addWidget(self._suggestion_chip(suggestion))
        return w

    def _suggestion_chip(self, text: str) -> QWidget:
        # Card background + visible outline: the previous fill matched the
        # page background in light mode, so the chips read as bare text.
        card_bg = theme.color("card_bg")
        card_hover = theme.color("sidebar_hover_bg")
        chip_fg = theme.color("text_primary")
        chip = QPushButton(f"  ●   {text}")
        chip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        chip.setMinimumWidth(360)
        chip.setStyleSheet(
            f"QPushButton {{ background-color: {card_bg}; color: {chip_fg}; "
            f"border: 1px solid {theme.color('border')}; "
            f"border-radius: 12px; padding: 12px 16px; "
            f"font-size: 15px; font-weight: 500; text-align: left; }}"
            f"QPushButton:hover {{ background-color: {card_hover}; "
            f"border-color: {theme.color('accent')}; }}")
        chip.clicked.connect(lambda _=False, s=text: self._use_suggestion(s))
        return chip

    def _build_api_missing_screen(self) -> QWidget:
        is_dark = theme.is_dark()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        icon = QLabel("⚠")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"font-size: 36px; color: {'#FBBF24' if is_dark else '#B45309'}; "
            f"background: transparent;")
        lay.addWidget(icon)

        title = QLabel("API Key Required")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 700; "
            f"color: {theme.color('text_primary')}; background: transparent;")
        lay.addWidget(title)

        desc = QLabel("Add an API key in Settings to start chatting.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 14px; color: {theme.color('text_secondary')}; "
            f"background: transparent;")
        lay.addWidget(desc)
        lay.addSpacing(12)

        btn = QPushButton("Open Settings")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(self._open_settings)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
        return w

    # ===================================================================
    #  Bubble helpers
    # ===================================================================
    def _add_user_bubble(self, text: str) -> _Bubble:
        bubble = _Bubble(is_user=True, max_width=self._bubble_widths()[0])
        bubble.set_text(text)
        self._insert_row(_BubbleRow(bubble, is_user=True))
        return bubble

    def _add_assistant_bubble(self, md: str | None = None) -> _Bubble:
        bubble = _Bubble(is_user=False, max_width=self._bubble_widths()[1])
        if md is not None:
            bubble.set_text(md)
        self._insert_row(_BubbleRow(bubble, is_user=False))
        return bubble

    def _insert_row(self, row: QWidget) -> None:
        # Insert before the trailing stretch so rows pack from the top.
        self._messages_lay.insertWidget(self._messages_lay.count() - 1, row)

    def _scroll_to_bottom(self) -> None:
        try:
            bar = self._scroll.verticalScrollBar()
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        except Exception:
            pass

    # ===================================================================
    #  Session management
    # ===================================================================
    def _ensure_session(self) -> None:
        if not self._history.get_active_id():
            self._history.create_session()

    def _save_current_session(self) -> None:
        active_id = self._history.get_active_id()
        if active_id and self.conversation_history:
            self._history.save_messages(active_id, self.conversation_history)

    def _finalize_in_flight_response(self, *, persist: bool = True) -> None:
        """Centralized cancel-and-persist for paths that interrupt a stream.

        The PARTIAL response is discarded and a fixed canned message is
        appended to history instead, exactly once (_response_persisted).
        """
        ctrl = self._stream_ctrl
        if ctrl is not None and ctrl.is_active:
            ctrl.cancel()
        if (persist
                and not getattr(self, "_response_persisted", False)
                and self._current_asst_bubble is not None
                and self._accumulated_text.strip()):
            self.conversation_history.append(
                {"role": "assistant", "content": _NAV_AWAY_MSG})
            self._response_persisted = True
        if self._current_asst_bubble is not None:
            try:
                self._current_asst_bubble.deleteLater()
            except Exception:
                pass
        self._current_asst_bubble = None
        self._accumulated_text = ""
        self._response_persisted = False
        try:
            self._unlock_input()
        except Exception:
            pass

    def _new_chat(self) -> None:
        self._finalize_in_flight_response(persist=True)
        # Don't orphan empty sessions from spammy "+ New" clicks.
        active_id = self._history.get_active_id()
        if active_id and not any(
                m.get("role") == "user"
                for m in self.conversation_history):
            self._history.delete_session(active_id)
        else:
            self._save_current_session()
        self.conversation_history = (
            [] if self.base_url else [dict(_SYS_MSG)])
        self.session_id = None
        self._history.create_session()
        self._rebuild_chat()

    def _select_chat(self, session_id: str) -> None:
        if session_id == self._history.get_active_id():
            return
        self._finalize_in_flight_response(persist=True)
        self._save_current_session()
        messages = self._history.load_messages(session_id)
        self.conversation_history = messages if messages else (
            [] if self.base_url else [dict(_SYS_MSG)])
        self._history.set_active_id(session_id)
        self._rebuild_chat()

    def _delete_chat(self, session_id: str) -> None:
        was_active = session_id == self._history.get_active_id()
        if was_active:
            self._finalize_in_flight_response(persist=False)
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
        """Clear and repopulate the message area for the active session."""
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        self._current_asst_bubble = None
        self._accumulated_text = ""
        self._response_persisted = False
        self._clear_welcome()
        # Remove every message row (keep the trailing stretch).
        while self._messages_lay.count() > 1:
            item = self._messages_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._restore_history()
        self._refresh_sidebar()

    # ===================================================================
    #  Sending / streaming
    # ===================================================================
    def send_message(self) -> None:
        if self.client is None:
            return
        user_text = self.chat_entry.text().strip()
        if not user_text:
            return
        if len(user_text) > 15000:
            try:
                self.app.show_notification(
                    "Message too long (15,000 character limit).",
                    type="warning")
            except Exception:
                pass
            return
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stop_streaming()
            return
        self._ensure_session()
        self._clear_welcome()
        self.chat_entry.clear()

        self._add_user_bubble(user_text)
        self._current_asst_bubble = self._add_assistant_bubble()
        self._scroll_to_bottom()
        self.conversation_history.append(
            {"role": "user", "content": user_text})

        self.chat_entry.setEnabled(False)
        self.send_button.setEnabled(True)
        self._style_send_button(stop=True)
        try:
            self.send_button.clicked.disconnect()
        except Exception:
            pass
        self.send_button.clicked.connect(self._stop_streaming)

        self._accumulated_text = ""
        self._response_persisted = False
        self._stream_ctrl = StreamController(
            app=self.app, on_chunk=self._on_stream_chunk,
            on_done=self._on_stream_done, on_error=self._on_stream_error)
        msgs = ([{"role": "user", "content": user_text}]
                if self.base_url else list(self.conversation_history))
        extra = ({"session_id": self.session_id}
                 if self.base_url and self.session_id else None)
        try:
            self._stream_ctrl.start(
                client=self.client, model=self.model, messages=msgs,
                temperature=0.7, extra_body=extra, base_url=self.base_url)
        except Exception as e:
            self._on_stream_error(str(e))

    def _stop_streaming(self) -> None:
        if self._stream_ctrl and self._stream_ctrl.is_active:
            self._stream_ctrl.cancel()
        if self._accumulated_text.strip() and self._current_asst_bubble:
            self._current_asst_bubble.set_text(self._accumulated_text)
            self.conversation_history.append(
                {"role": "assistant", "content": self._accumulated_text})
        elif self._current_asst_bubble is not None:
            self._current_asst_bubble.setParent(None)
            self._current_asst_bubble.deleteLater()
        self._current_asst_bubble = None
        self._unlock_input()
        self._save_current_session()
        self._refresh_sidebar()

    def _on_stream_chunk(self, chunk_text: str) -> None:
        self._accumulated_text += chunk_text
        if self._current_asst_bubble is not None:
            self._current_asst_bubble.set_text(self._accumulated_text)
        self._scroll_to_bottom()

    def _on_stream_done(self, full_text: str) -> None:
        if getattr(self, "_response_persisted", False):
            return
        if self._current_asst_bubble is not None:
            if not full_text.strip():
                # Empty SSE: server closed the stream without content. Show a
                # user-facing message instead of a blank bubble, and unlock.
                self._current_asst_bubble.set_text(
                    "No response received from the server. "
                    "Please try again in a moment.")
                self._current_asst_bubble = None
                self._response_persisted = True
                try:
                    self.app.show_notification(
                        "The server returned an empty response.",
                        type="warning")
                except Exception:
                    pass
            else:
                self._current_asst_bubble.set_text(full_text)
                self._current_asst_bubble = None
                self.conversation_history.append(
                    {"role": "assistant", "content": full_text})
                self._response_persisted = True
        self._unlock_input()
        self._save_current_session()
        self._refresh_sidebar()
        self._scroll_to_bottom()

    def _on_stream_error(self, error_msg: str) -> None:
        if getattr(self, "_response_persisted", False):
            return
        if (self._accumulated_text.strip()
                and self._current_asst_bubble is not None):
            self._current_asst_bubble.set_text(self._accumulated_text)
            self.conversation_history.append(
                {"role": "assistant", "content": self._accumulated_text})
            try:
                self.app.show_notification(
                    "Response may be incomplete.", type="warning")
            except Exception:
                pass
        elif self._current_asst_bubble is not None:
            try:
                self._current_asst_bubble.set_text(f"Error: {error_msg}")
            except Exception:
                pass
        self._current_asst_bubble = None
        self._unlock_input()
        self._save_current_session()

    def _unlock_input(self) -> None:
        try:
            self.chat_entry.setEnabled(True)
            self._style_send_button(stop=False)
            self.send_button.setEnabled(True)
            try:
                self.send_button.clicked.disconnect()
            except Exception:
                pass
            self.send_button.clicked.connect(self.send_message)
            self.chat_entry.setFocus()
        except Exception:
            pass

    # ===================================================================
    #  Misc
    # ===================================================================
    def _sync_input_enabled(self) -> None:
        """Enable/disable the input controls to match client availability."""
        entry = getattr(self, "chat_entry", None)
        btn = getattr(self, "send_button", None)
        if entry is None or btn is None:
            return
        if self.client is None:
            entry.setEnabled(False)
            entry.setPlaceholderText("API key required — see Settings")
            btn.setEnabled(False)
        else:
            entry.setEnabled(True)
            entry.setPlaceholderText("Message Resistine AI...")
            btn.setEnabled(True)

    def _use_suggestion(self, text: str) -> None:
        if self.client is None:
            return
        self.chat_entry.setText(text)
        self.send_message()

    def _open_settings(self) -> None:
        try:
            sp = next((p for p in self.app.plugin_list
                       if p.get_name() == "Settings"), None)
            if sp:
                self.app.select_frame_by_name(
                    "frame_Settings", button=sp.get_button())
        except Exception:
            pass

    def on_theme_changed(self) -> None:
        """Rebuild the chat screen — the drawer, top bar and bubbles resolve
        theme colours at build time, so a mode toggle otherwise leaves the
        history drawer (and friends) painted in the previous mode."""
        try:
            self._save_current_session()
        except Exception:
            pass
        try:
            self.app.update_plugin(self.id)
        except Exception:
            logger.debug("Chat: theme rebuild failed")

    def destroy(self) -> None:
        """Plugin teardown — cancel any in-flight stream and flush state."""
        try:
            self._finalize_in_flight_response(persist=True)
        except Exception:
            pass
        try:
            self._save_current_session()
        except Exception:
            pass
