"""Welcome screen, suggestion chips, and API-key-missing screen for the chat plugin."""

from __future__ import annotations

import random
from typing import Callable

import customtkinter

# Pool of suggestion prompts shown on the welcome screen.
# 4 are picked at random each time the chat is opened.
SUGGESTION_POOL = [
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

_RESISTINE_BLUE = "#0D5394"


def _secondary_color(is_dark: bool) -> str:
    return "#9CA3AF" if is_dark else "#6B7280"


def _divider_color(is_dark: bool) -> str:
    return "#2A2A2A" if is_dark else "#E5E7EB"


class WelcomeScreen(customtkinter.CTkFrame):
    """Centered welcome overlay with greeting and suggestion chips.

    When the user clicks a suggestion chip, *on_suggestion_click* is called
    with the suggestion text so the caller can inject it into the chat.
    """

    def __init__(
        self,
        master: customtkinter.CTkBaseClass,
        on_suggestion_click: Callable[[str], None],
        is_dark: bool = False,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        self._on_suggestion_click = on_suggestion_click

        fg_color = "#ffffff" if is_dark else "#000000"
        secondary = _secondary_color(is_dark)
        card_bg = "#1A1A1C" if is_dark else "#ffffff"
        card_hover = "#242426" if is_dark else "#F0F0F5"
        divider = _divider_color(is_dark)

        # Greeting
        greeting_label = customtkinter.CTkLabel(
            self,
            text="Resistine AI",
            font=customtkinter.CTkFont(family="Inter", size=26, weight="bold"),
            text_color=_RESISTINE_BLUE,
        )
        greeting_label.pack(pady=(0, 4))

        subtitle_label = customtkinter.CTkLabel(
            self,
            text="Your AI security assistant. Ask me anything.",
            font=customtkinter.CTkFont(family="Inter", size=14),
            text_color=secondary,
        )
        subtitle_label.pack(pady=(0, 28))

        # Pick 4 random suggestions from the pool
        suggestions = random.sample(
            SUGGESTION_POOL, min(4, len(SUGGESTION_POOL))
        )

        chips_frame = customtkinter.CTkFrame(self, fg_color="transparent")
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
                border_color=divider,
                height=44,
                width=260,
                anchor="w",
                command=lambda s=suggestion: self._on_suggestion_click(s),
            )
            chip.grid(row=row, column=col, padx=6, pady=6)


class ApiKeyMissingScreen(customtkinter.CTkFrame):
    """Centered overlay telling the user to configure an API key.

    When the user clicks the settings button, *on_configure_click* is called
    so the caller can navigate to the settings screen.
    """

    def __init__(
        self,
        master: customtkinter.CTkBaseClass,
        on_configure_click: Callable[[], None],
        is_dark: bool = False,
        **kwargs,
    ) -> None:
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(master, **kwargs)

        self._on_configure_click = on_configure_click

        secondary = _secondary_color(is_dark)
        error_color = "#FBBF24" if is_dark else "#B45309"

        icon_label = customtkinter.CTkLabel(
            self,
            text="\u26A0",
            font=customtkinter.CTkFont(size=36),
            text_color=error_color,
        )
        icon_label.pack(pady=(0, 8))

        title_label = customtkinter.CTkLabel(
            self,
            text="API Key Required",
            font=customtkinter.CTkFont(family="Inter", size=20, weight="bold"),
            text_color="#ffffff" if is_dark else "#000000",
        )
        title_label.pack(pady=(0, 6))

        desc_label = customtkinter.CTkLabel(
            self,
            text="Add your OpenAI API key in Settings to start chatting.",
            font=customtkinter.CTkFont(family="Inter", size=14),
            text_color=secondary,
        )
        desc_label.pack(pady=(0, 20))

        settings_btn = customtkinter.CTkButton(
            self,
            text="Open Settings",
            font=customtkinter.CTkFont(family="Inter", size=13, weight="bold"),
            fg_color=_RESISTINE_BLUE,
            hover_color="#1565B0",
            text_color="#ffffff",
            corner_radius=10,
            height=40,
            width=160,
            command=self._on_configure_click,
        )
        settings_btn.pack()
