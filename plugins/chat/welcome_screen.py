"""Welcome screen, suggestion chips, and API-key-missing screen for the chat plugin."""

from __future__ import annotations

import random
from typing import Callable

import customtkinter

from plugins.chat.fonts import RESISTINE_BLUE, ui_family

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
        card_bg = "#2A2A2C" if is_dark else "#F5F5F7"
        card_hover = "#353538" if is_dark else "#E8E8EC"
        chip_fg = "#e0e0e0" if is_dark else "#1a1a1a"
        arrow_fg = "#6B7280" if is_dark else "#9CA3AF"

        # Greeting
        greeting_label = customtkinter.CTkLabel(
            self,
            text="How can I help you today?",
            font=customtkinter.CTkFont(
                family=ui_family(), size=24, weight="bold"),
            text_color=fg_color,
        )
        greeting_label.pack(pady=(0, 4))

        subtitle_label = customtkinter.CTkLabel(
            self,
            text="Ask me anything about cybersecurity",
            font=customtkinter.CTkFont(family=ui_family(), size=14),
            text_color=secondary,
        )
        subtitle_label.pack(pady=(0, 28))

        # Pick 4 random suggestions from the pool
        suggestions = random.sample(
            SUGGESTION_POOL, min(4, len(SUGGESTION_POOL))
        )

        # Measure longest text to set uniform chip width
        import tkinter.font as tkfont
        measure_font = tkfont.Font(family=ui_family(), size=13)
        longest_px = max(measure_font.measure(s) for s in suggestions)
        # dot(16+18) + text + arrow(20+18) + padding
        chip_width = longest_px + 100

        # Container for TRY ASKING + chips, centered
        chips_box = customtkinter.CTkFrame(
            self, fg_color="transparent", width=chip_width)
        chips_box.pack(pady=0)

        section_label = customtkinter.CTkLabel(
            chips_box, text="TRY ASKING",
            font=customtkinter.CTkFont(
                family=ui_family(), size=11, weight="bold"),
            text_color=RESISTINE_BLUE, anchor="w",
        )
        section_label.pack(anchor="w", pady=(16, 8))

        for suggestion in suggestions:
            chip = customtkinter.CTkFrame(
                chips_box, fg_color=card_bg, corner_radius=12,
                width=chip_width, height=48, cursor="hand2")
            chip.pack(pady=4)
            chip.pack_propagate(False)

            # Bullet dot
            dot = customtkinter.CTkLabel(
                chip, text="\u25CF", width=18,
                font=customtkinter.CTkFont(size=8),
                text_color=RESISTINE_BLUE, fg_color="transparent")
            dot.pack(side="left", padx=(14, 4), pady=8)

            # Suggestion text
            lbl = customtkinter.CTkLabel(
                chip, text=suggestion,
                font=customtkinter.CTkFont(family=ui_family(), size=13),
                text_color=chip_fg, fg_color="transparent",
                anchor="w", justify="left")
            lbl.pack(side="left", fill="x", expand=True, pady=8)

            # Arrow
            arrow = customtkinter.CTkLabel(
                chip, text=">", width=20,
                font=customtkinter.CTkFont(size=16),
                text_color=arrow_fg, fg_color="transparent")
            arrow.pack(side="right", padx=(4, 14), pady=8)

            # Click bindings on all children
            for widget in (chip, dot, lbl, arrow):
                widget.bind(
                    "<Button-1>",
                    lambda _e, s=suggestion: self._on_suggestion_click(s))
                widget.configure(cursor="hand2")

            # Hover effect
            def _enter(e, c=chip, bg=card_hover):
                c.configure(fg_color=bg)

            def _leave(e, c=chip, bg=card_bg):
                c.configure(fg_color=bg)

            for widget in (chip, dot, lbl, arrow):
                widget.bind("<Enter>", _enter)
                widget.bind("<Leave>", _leave)


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
            font=customtkinter.CTkFont(family=ui_family(), size=20, weight="bold"),
            text_color="#ffffff" if is_dark else "#000000",
        )
        title_label.pack(pady=(0, 6))

        desc_label = customtkinter.CTkLabel(
            self,
            text="Add your OpenAI API key in Settings to start chatting.",
            font=customtkinter.CTkFont(family=ui_family(), size=14),
            text_color=secondary,
        )
        desc_label.pack(pady=(0, 20))

        settings_btn = customtkinter.CTkButton(
            self,
            text="Open Settings",
            font=customtkinter.CTkFont(family=ui_family(), size=13, weight="bold"),
            fg_color=RESISTINE_BLUE,
            hover_color="#1565B0",
            text_color="#ffffff",
            corner_radius=10,
            height=40,
            width=160,
            command=self._on_configure_click,
        )
        settings_btn.pack()
