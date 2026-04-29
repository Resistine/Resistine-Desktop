"""Shared markdown utilities for the chat plugin."""
from __future__ import annotations

import re

_BOX_CHARS = frozenset("\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c\u2500\u2502\u256d\u256e\u256f\u2570\u2571\u2572\u25b2\u25bc\u25c4\u25ba\u2550\u2551\u2554\u2557\u255a\u255d\u2560\u2563\u2566\u2569\u256c")


def is_box_drawing(line: str) -> bool:
    """Return True if *line* looks like an ASCII art / box diagram."""
    return bool(line and _BOX_CHARS.intersection(line))


def strip_inline_md(text: str) -> str:
    """Strip inline markdown markers, returning plain text."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\([^)]+\)', r'\1', text)
    return text
