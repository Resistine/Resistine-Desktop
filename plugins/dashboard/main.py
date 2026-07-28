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

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.qt_widgets import FlowLayout, StatusBadge
from plugins.base_plugin import BasePlugin

_DIR = os.path.dirname(os.path.realpath(__file__))


class _PluginCard(QFrame):
    """Mirror of create_plugin_card: icon left, title + badge, description.

    Sizes below are BASE values at scale 1.0; ``apply_scale`` grows the tile
    and its content together so the grid can fill the viewport height (see
    ``Plugin._rescale``)."""

    BASE_W, BASE_H = 260, 304
    BASE_ICON = 46
    BASE_TITLE = 16
    BASE_DESC = 13
    BASE_MARGIN = 16
    BASE_SPACING = 8
    BASE_HEADER_SPACING = 12

    def __init__(self, plugin, on_click):
        super().__init__()
        self._plugin = plugin
        self._on_click = on_click
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._outer = QVBoxLayout(self)
        self._header = QHBoxLayout()
        self._icon = QLabel()
        self._header.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self._title = QLabel(plugin.get_name())
        title_col.addWidget(self._title)
        badge_row = QHBoxLayout()
        badge_row.addWidget(StatusBadge(plugin.get_status()))
        badge_row.addStretch(1)
        title_col.addLayout(badge_row)
        self._header.addLayout(title_col, 1)
        self._outer.addLayout(self._header)

        self._desc = QLabel(plugin.get_description())
        self._desc.setWordWrap(True)
        self._outer.addWidget(self._desc)
        self._outer.addStretch(1)

        self.apply_scale(1.0)

    def apply_scale(self, scale: float) -> None:
        """Resize the tile + its content by ``scale`` (1.0 == base)."""
        def s(base):
            return max(1, round(base * scale))

        self.setFixedSize(s(self.BASE_W), s(self.BASE_H))
        ic = s(self.BASE_ICON)
        self._icon.setPixmap(self._plugin.get_icon_pixmap(ic))
        self._icon.setFixedSize(ic, ic)
        self._title.setStyleSheet(
            f"font-size: {s(self.BASE_TITLE)}px; font-weight: 700;")
        self._desc.setStyleSheet(
            f"color: {theme.color('text_secondary')}; "
            f"font-size: {s(self.BASE_DESC)}px;")
        m = s(self.BASE_MARGIN)
        self._outer.setContentsMargins(m, m, m, m)
        self._outer.setSpacing(s(self.BASE_SPACING))
        self._header.setSpacing(s(self.BASE_HEADER_SPACING))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class _FillScrollArea(QScrollArea):
    """Scroll page that reports its resizes (debounced) so the dashboard can
    grow its tiles to fill the viewport height."""

    def __init__(self, on_resize):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._on_resize = on_resize
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(50)
        self._debounce.timeout.connect(self._on_resize)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._debounce.start()


class Plugin(BasePlugin):
    """Dashboard plugin."""

    def __init__(self, app):
        super().__init__(
            id="001", version="2025.01.01", order=1, name="Dashboard",
            status=None,
            description="See your protection status at a glance.",
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
            banner.setText("✓  Protected")
            banner.setProperty("protection", "ok")
        else:
            banner.setText("⚠  Not Protected")
            banner.setProperty("protection", "warn")
        v.addWidget(banner)
        v.addSpacing(16)

        # Reflowing, centered grid targeting THREE columns (max_cols=3),
        # wrapping to fewer when narrow. Tiles grow to fill the viewport
        # height (see _rescale) so there's no empty space below the last row.
        host = QWidget()
        self._flow = FlowLayout(host, margin=0, spacing=16, center=True,
                                max_cols=3)
        self._grid_host = host
        self._tiles = []
        for p in self._cards():
            card = _PluginCard(p, lambda n=p.get_name():
                               self.app.select_frame_by_name(f"frame_{n}"))
            self._flow.addWidget(card)
            self._tiles.append(card)
        v.addWidget(host)
        v.addStretch(1)

        self._scroll = _FillScrollArea(self._rescale)
        self._scroll.setWidget(inner)
        self.app.after(0, self._rescale)  # initial fill once laid out
        return self._scroll

    def _rescale(self) -> None:
        """Grow the tiles + content so the rows fill the viewport height (no
        empty space past the last tile). Grow-only, and capped so the scaled
        tiles still fit their column count horizontally."""
        tiles = getattr(self, "_tiles", None)
        host = getattr(self, "_grid_host", None)
        scroll = getattr(self, "_scroll", None)
        if not tiles or host is None or scroll is None:
            return
        try:
            vp_h = scroll.viewport().height()
            top = host.mapTo(scroll.viewport(), QPoint(0, 0)).y()
            avail_w = host.width()
        except RuntimeError:
            return
        gap = 16
        base_w, base_h = _PluginCard.BASE_W, _PluginCard.BASE_H
        cols = max(1, min(3, (avail_w + gap) // (base_w + gap)))
        rows = -(-len(tiles) // cols)  # ceil
        natural_h = rows * base_h + (rows - 1) * gap
        natural_w = cols * base_w + (cols - 1) * gap
        avail_h = vp_h - top - 20  # 20 == inner bottom margin
        if natural_h <= 0 or natural_w <= 0:
            return
        # Fill the height, but never so much that a row overflows the width.
        scale = min(avail_h / natural_h, avail_w / natural_w)
        scale = max(1.0, min(scale, 2.0))  # grow-only, capped
        for card in tiles:
            try:
                card.apply_scale(scale)
            except RuntimeError:
                return
        self._flow.invalidate()
        host.updateGeometry()

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
