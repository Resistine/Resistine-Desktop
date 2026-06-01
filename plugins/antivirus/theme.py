"""Layout helpers for the Antivirus plugin.

This module deliberately defines no colors — widgets here either rely on
their CustomTkinter defaults (which come from the app-wide theme JSON at
resources/themes/resistine_ctk.json) or read named tokens from
ThemeManager at call time. That way the antivirus page tracks any
app-wide palette change without a parallel set of constants.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import customtkinter
from customtkinter import ThemeManager

CORNER_R = 12
PAD_X = 20
_FONT_FAMILY = "Inter"

# Palette tuples (light, dark) mirroring tokens in resistine_ctk.json.
# Kept as module constants so ui_cards.py and main.py can import them;
# values are evaluated once at widget-construction time, which is fine
# because theme switches trigger a full main-screen rebuild.
COLOR_MUTED = ("#6B7280", "#9CA3AF")          # text_secondary
COLOR_OK_TEXT = ("#15803D", "#4ADE80")        # protection_text_ok
COLOR_BTN_OUTLINE = ("#0D5394", "#60A5FA")    # sidebar_active_text
COLOR_BTN_OUTLINE_HOVER = ("#DBEAFE", "#1E3A5F")
COLOR_CARD_BG = None                          # use CTk default
COLOR_CARD_BORDER = None                      # use CTk default


# CTkFont objects are surprisingly expensive to instantiate on macOS — each
# call walks Tk's font registry. The same (size, weight) combination gets
# requested dozens of times during a single plugin build, so cache them.
# Theme tuples are static for a given appearance mode; if appearance changes
# the cache is invalidated via clear_theme_cache() (called from
# refresh_ui_theme in gui/user_interface.py).
_FONT_CACHE: dict = {}
_THEME_CACHE: dict = {}


def font(size, bold=False, family=None):
    family = family or _FONT_FAMILY
    key = (family, size, bold)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    weight = "bold" if bold else "normal"
    obj = customtkinter.CTkFont(family=family, size=size, weight=weight)
    _FONT_CACHE[key] = obj
    return obj


def _theme_token(name: str):
    cached = _THEME_CACHE.get(name)
    if cached is not None:
        return cached
    value = ThemeManager.theme.get("Theme", {}).get(name)
    _THEME_CACHE[name] = value
    return value


def clear_theme_cache():
    """Invalidate the font + theme-token caches.

    Called from gui.user_interface.refresh_ui_theme() so theme switches pick
    up new colors. The plugin's full widget tree is rebuilt right after, so
    the next builder pass repopulates the caches.
    """
    _FONT_CACHE.clear()
    _THEME_CACHE.clear()


def make_card(parent, row):
    card = customtkinter.CTkFrame(
        parent, corner_radius=CORNER_R, border_width=1,
    )
    card.grid(row=row, column=0, sticky="ew", padx=PAD_X, pady=(0, 6))
    card.grid_columnconfigure(0, weight=1)
    return card


def add_separator(card, row):
    customtkinter.CTkFrame(
        card, height=1, fg_color=_theme_token("divider_color"),
    ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=16)
    return row + 1


def section_title(parent, text):
    return customtkinter.CTkLabel(
        parent, text=text.upper(),
        font=font(12, bold=True),
        text_color=_theme_token("sidebar_active_text"),
    )
