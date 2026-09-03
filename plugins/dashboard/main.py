## @file plugins/dashboard/main.py
## @namespace dashboard_plugin
"""Dashboard plugin UI (PyQt6) — faithful port of the CTk layout.

A protection-status banner above a responsive grid of plugin cards (icon, title,
status badge, description). Clicking a card navigates to that plugin. No page
title/section heading — same as the original.

Author: P3, Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.qt_widgets import CardGrid, StatusBadge, scroll_page
from plugins.base_plugin import BasePlugin
from utils.i18n import get_text

_DIR = os.path.dirname(os.path.realpath(__file__))


class _PluginCard(QFrame):
    """Mirror of create_plugin_card: icon left, title + badge, description."""

    def __init__(self, plugin, on_click):
        super().__init__()
        self._on_click = on_click
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Cards stretch to fill their grid cell so the dashboard uses the
        # whole width (CTk parity: column weights, not fixed tiles).
        self.setMinimumSize(230, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(plugin.get_icon_pixmap(48))
        icon.setFixedSize(48, 48)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel(plugin.get_display_name())
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        title_col.addWidget(title)
        badge_row = QHBoxLayout()
        badge_row.addWidget(StatusBadge(plugin.get_status()))
        badge_row.addStretch(1)
        title_col.addLayout(badge_row)
        header.addLayout(title_col, 1)
        outer.addLayout(header)

        desc = QLabel(plugin.get_description())
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.color('text_secondary')};")
        outer.addWidget(desc)
        outer.addStretch(1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class Plugin(BasePlugin):
    """Dashboard plugin."""

    def __init__(self, app):
        super().__init__(
            id="001", version="2025.01.01", order=1, name="Dashboard",
            status=None,
            description=get_text("dashboard.see_your_protection_status_at"),
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Dashboard", "ES": "Panel",
                          "FR": "Tableau de bord"},
            icon_light_path=os.path.join(_DIR, "home_light.png"),
            icon_dark_path=os.path.join(_DIR, "home_dark.png"),
            uninstall_enabled=False,
        )
        self.app = app

    def create_main_screen(self):
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(20, 16, 20, 20)
        v.setSpacing(0)

        # Protection banner (mirrors the CTk 48px coloured bar).
        banner = QLabel()
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setMinimumHeight(48)
        if self._vpn_ok():
            banner.setText(get_text("dashboard.protected"))
            banner.setProperty("protection", "ok")
        else:
            banner.setText(get_text("dashboard.not_protected"))
            banner.setProperty("protection", "warn")
        v.addWidget(banner)
        v.addSpacing(16)

        # Responsive card grid: column count follows the width ladder and the
        # cards stretch to fill each cell — no dead gutters at any size.
        host = CardGrid()
        host.set_cards([
            _PluginCard(p, lambda n=p.get_name():
                        self.app.select_frame_by_name(f"frame_{n}"))
            for p in self._cards()
        ])
        v.addWidget(host, 1)
        return scroll_page(inner)

    def on_theme_changed(self) -> None:
        """Rebuild the screen so card icons/colours re-tint for the new theme.

        Cards bake the tinted icon pixmap and secondary-text colour in at
        build time — without a rebuild a theme toggle leaves dark icons on
        dark cards (same bug the Store had).
        """
        try:
            self.app.update_plugin()  # rebuilds the Dashboard screen
        except Exception:
            pass

    def _cards(self):
        from utils import settings as app_settings
        plugins = getattr(self.app, "plugins", [])
        # Login (order 0) is normally hidden from the grid, but when the user
        # is logged out it appears as a clear call-to-action to sign back in.
        logged_in = app_settings.get("auth", "logged_in", False)
        return [
            p for p in plugins
            if p.get_name() != "Dashboard"
            and (p.order > 0
                 or (not logged_in and getattr(p, "id", None) == "007"))
        ]

    def _vpn_ok(self) -> bool:
        vpn = next((p for p in getattr(self.app, "plugins", [])
                    if p.get_name() == "VPN"), None)
        try:
            return bool(vpn and vpn.get_status() == "OK")
        except Exception:
            return False
