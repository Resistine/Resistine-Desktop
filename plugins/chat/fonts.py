"""Named tkFont.Font registry for the chat plugin.

Canonical source for every font and colour used in chat bubbles.
All font usage goes through named Font objects derived from a single
base size, which fixes the "oversized bold" bug.

Author: P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import sys
import tkinter as _tk
import tkinter.font as tkFont

import customtkinter

RESISTINE_BLUE = "#0D5394"

# -- Base metrics (px) --------------------------------------------------------
_BASE_SIZE = 15
_MONO_FAMILY = "Menlo" if sys.platform == "darwin" else "Consolas"
_BODY_FAMILY = "Inter"
_HEADING_SIZES = {"h1": 20, "h2": 18, "h3": 16, "h4": 15, "h5": 14, "h6": 13}

# -- Internal state -----------------------------------------------------------
_font_cache: dict[str, tkFont.Font] | None = None


def _is_dark_mode() -> bool:
    """Detect whether the current CTk appearance mode is dark."""
    mode = customtkinter.get_appearance_mode()
    if mode == "Dark":
        return True
    if mode == "Light":
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


def _named(name: str, **kw: object) -> tkFont.Font:
    """Create or retrieve a named Tk font."""
    try:
        return tkFont.Font(name=name, exists=True)
    except _tk.TclError:
        return tkFont.Font(name=name, exists=False, **kw)


def get_fonts(is_dark: bool = False) -> dict[str, tkFont.Font]:
    """Return a dict of named ``tkFont.Font`` objects for the chat UI.

    Fonts are created once and cached.  Calling again returns the same
    objects so ``tag_configure`` can reference the name strings directly.
    """
    global _font_cache
    if _font_cache is not None:
        return _font_cache

    fonts: dict[str, tkFont.Font] = {
        "body": _named(
            "chat_body", family=_BODY_FAMILY, size=_BASE_SIZE,
        ),
        "bold": _named(
            "chat_bold", family=_BODY_FAMILY, size=_BASE_SIZE, weight="bold",
        ),
        "italic": _named(
            "chat_italic", family=_BODY_FAMILY, size=_BASE_SIZE, slant="italic",
        ),
        "bold_italic": _named(
            "chat_bold_italic", family=_BODY_FAMILY, size=_BASE_SIZE,
            weight="bold", slant="italic",
        ),
        "code": _named(
            "chat_code", family=_MONO_FAMILY, size=_BASE_SIZE,
        ),
        "link": _named(
            "chat_link", family=_BODY_FAMILY, size=_BASE_SIZE, underline=True,
        ),
        "strikethrough": _named(
            "chat_strike", family=_BODY_FAMILY, size=_BASE_SIZE, overstrike=True,
        ),
    }
    for tag, sz in _HEADING_SIZES.items():
        fonts[tag] = _named(
            f"chat_{tag}", family=_BODY_FAMILY, size=sz, weight="bold",
        )

    _font_cache = fonts
    return fonts


def get_theme_colors(is_dark: bool) -> dict[str, str]:
    """Return a dict of colour strings keyed by semantic role."""
    if is_dark:
        return {
            "bg": "transparent",
            "fg": "#e0e0e0",
            "bubble_bg": "#2E2E32",
            "bubble_fg": "#e0e0e0",
            "user_bubble_bg": "#0D5394",
            "user_bubble_fg": "#FFFFFF",
            "code_bg": "#2A2A2C",
            "code_fg": "#d4d4d4",
            "code_header_bg": "#252528",
            "link": "#60A5FA",
            "heading": "#FFFFFF",
            "blockquote_bar": "#9CA3AF",
            "hr": "#2A2A2A",
            "table_header_bg": "#252528",
            "table_alt_bg": "#1E1E20",
        }
    return {
        "bg": "transparent",
        "fg": "#1a1a1a",
        "bubble_bg": "#F7F7F9",
        "bubble_fg": "#1a1a1a",
        "user_bubble_bg": "#0D5394",
        "user_bubble_fg": "#FFFFFF",
        "code_bg": "#F5F5F7",
        "code_fg": "#333333",
        "code_header_bg": "#E8E8EA",
        "link": "#0D5394",
        "heading": "#111111",
        "blockquote_bar": "#6B7280",
        "hr": "#E5E7EB",
        "table_header_bg": "#E8E8EA",
        "table_alt_bg": "#F5F5F7",
    }
