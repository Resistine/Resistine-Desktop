# @file plugins/store/main.py
"""Store plugin (PyQt6) — faithful port of the CTk layout.

Top spacer, a centered "Store" title panel (a card whose title is large/bold,
constrained to ~50% width and centered), then a reflowing grid of plugin cards
(icon + title + status badge + description) with injected store action buttons:
Info + Install (downloadable / uninstalled) or Uninstall (installed +
uninstall_enabled) with an inline Confirm/Cancel step; "Installed"/"Core" states
have no action button.

The full plugin list depends on a NETWORK fetch (get_available_plugins). That
fetch runs on a worker thread and is marshalled back via app.after(0, ...) — the
build never blocks on it. Installed/local cards render immediately and remote-only
ones fold in when they arrive, exactly like the original.

Author: Peres J., P3 and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import os
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QSizePolicy,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.qt_widgets import CardGrid, StatusBadge, scroll_page
from plugins.base_plugin import BasePlugin

_DIR = os.path.dirname(os.path.realpath(__file__))

# Plugins hidden from the Store (still available in sidebar if installed).
HIDDEN_FROM_STORE = {"001", "004", "009", "010", "100"}  # Dashboard, Store, Help, Settings, Calculator
HIDDEN_NAMES = {"template"}  # Also hide by name for remote-only plugins


# Store action button colours (light, dark) lifted from the CTk original.
def _btn_style(light_bg, dark_bg, light_hover, dark_hover) -> str:
    bg = dark_bg if theme.is_dark() else light_bg
    hover = dark_hover if theme.is_dark() else light_hover
    return (
        f"QPushButton {{ background-color: {bg}; color: white; border: none; "
        f"border-radius: 8px; padding: 7px 12px; font-size: 12px; "
        f"font-weight: 600; }} "
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )


_INFO_STYLE = _btn_style("#3B8ED0", "#1F6AA5", "#367EBB", "#144870")
_INSTALL_STYLE = _btn_style("#2ECC71", "#27AE60", "#27AE60", "#219150")
_UNINSTALL_STYLE = _btn_style("#FF4444", "#C73636", "#C73636", "#9E2A2A")
_CANCEL_STYLE = _btn_style("#808080", "#606060", "#707070", "#505050")


class _StoreCard(QFrame):
    """Mirror of the Dashboard card (icon 48 + title + StatusBadge + description),
    with the store action buttons added at the bottom."""

    def __init__(self, plugin, inject_buttons):
        super().__init__()
        self.setObjectName("Card")
        # Cards stretch to fill their grid cell (same behaviour as the
        # Dashboard grid) instead of fixed-size tiles with dead gutters.
        self.setMinimumSize(230, 230)
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
        title = QLabel(plugin.get_name())
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

        # Injected store action buttons (Info + Install/Uninstall/...).
        self.button_row = QHBoxLayout()
        self.button_row.setSpacing(8)
        outer.addLayout(self.button_row)
        inject_buttons(self, plugin)

    def clear_buttons(self) -> None:
        while self.button_row.count():
            item = self.button_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()


class Plugin(BasePlugin):
    """Store plugin — download and install new plugins."""

    # Kept for source compatibility with the CTk reveal cascade.
    defer_reveal_until_settled = True

    def __init__(self, app):
        super().__init__(
            id="004",
            version="2025.01.01",
            order=1000,
            name="Store",
            status=None,
            description="This plugin allows you to download and install new plugins.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Store", "ES": "Tienda", "FR": "Magasin"},
            icon_light_path=os.path.join(_DIR, "store_light.png"),
            icon_dark_path=os.path.join(_DIR, "store_dark.png"),
            uninstall_enabled=False,
        )
        self.app = app
        self.status = self.get_status()
        self.plugin_cards: dict = {}
        self.remote_data_map: dict = {}

    # ===================================================================
    #  Screen
    # ===================================================================
    def create_main_screen(self):
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(20, 0, 20, 20)
        col.setSpacing(0)

        # 1. Top spacer — move content down, away from the header.
        col.addSpacing(30)

        # 2. Centered "Store" title panel (a card, ~50% width, centered).
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addStretch(1)
        title_panel = QFrame()
        title_panel.setObjectName("Surface")
        tp_lay = QVBoxLayout(title_panel)
        tp_lay.setContentsMargins(20, 20, 20, 20)
        self.title_label = QLabel("Store")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # No inline color — inherit the app-wide QSS `QWidget { color: … }`,
        # which is re-applied on every theme toggle. Baking text_primary in
        # here froze the title at its build-time colour across theme changes.
        self.title_label.setStyleSheet("font-size: 30px; font-weight: 700;")
        tp_lay.addWidget(self.title_label)
        title_row.addWidget(title_panel, 1)  # ~50% via the two stretches
        title_row.addStretch(1)
        col.addLayout(title_row)
        col.addSpacing(20)

        # 3. Responsive grid of plugin cards. Build with whatever remote data we
        #    already have (cached from a prior visit, or empty). The remote list
        #    is a network fetch, so we NEVER block the build on it — render local
        #    plugins now and fold remote-only ones in when they arrive.
        available_remote = getattr(self, "_remote_cache", None)
        plugins = self._build_plugin_list(available_remote or [])
        self._remote_done = available_remote is not None
        self._store_plugins = plugins

        self._grid_host = CardGrid()
        self._flow = self._grid_host  # FlowLayout-compatible surface
        self.plugin_cards = {}
        for p in plugins:
            self._add_card(p)
        col.addWidget(self._grid_host, 1)

        self.main_frame = scroll_page(inner)

        # 4. On the first visit, fetch the remote plugin list in the background.
        if available_remote is None:
            self._fetch_remote_async()
            self.app.after(2500, self._mark_remote_done)

        return self.main_frame

    def is_screen_ready(self):
        return getattr(self, "_remote_done", True)

    def _mark_remote_done(self):
        self._remote_done = True

    def _add_card(self, plugin) -> None:
        card = _StoreCard(plugin, self._inject_store_buttons)
        self._flow.addWidget(card)
        self.plugin_cards[plugin.id] = card

    # ===================================================================
    #  Plugin list composition (NO network I/O — safe on the build path)
    # ===================================================================
    def _build_plugin_list(self, available_remote):
        try:
            manager = self.app.get_plugin_manager()
            installed_plugins = manager.plugins
            all_local_plugins = manager.load_plugins(include_uninstalled=True)
        except Exception:
            installed_plugins = list(getattr(self.app, "plugins", []))
            all_local_plugins = list(installed_plugins)

        installed_ids = {p.id for p in installed_plugins}
        local_ids = {p.id for p in all_local_plugins}

        plugins = list(installed_plugins)
        for lp in all_local_plugins:
            if lp.id not in installed_ids:
                lp.status = "Uninstalled"
                plugins.append(lp)
        for rp in available_remote:
            if rp["id"] not in local_ids:
                plugins.append(RemotePluginWrapper(self.app, rp))

        # Keep remote data for restoration after uninstall.
        self.remote_data_map = {rp["id"]: rp for rp in available_remote}

        plugins = [
            p for p in plugins
            if p.id not in HIDDEN_FROM_STORE
            and getattr(p, "name", "").lower() not in HIDDEN_NAMES
        ]

        # Local/installed first (sorted by name), then remote-only (sorted) — so
        # folding remote in later never reorders the local cards already on
        # screen; the remote cards simply append after them.
        local = sorted(
            (p for p in plugins if not isinstance(p, RemotePluginWrapper)),
            key=lambda x: x.get_name(),
        )
        remote_only = sorted(
            (p for p in plugins if isinstance(p, RemotePluginWrapper)),
            key=lambda x: x.get_name(),
        )
        plugins = local + remote_only

        unique_plugins, seen = [], set()
        for p in plugins:
            if p.id not in seen:
                unique_plugins.append(p)
                seen.add(p.id)
        return unique_plugins

    # ===================================================================
    #  Async remote fetch
    # ===================================================================
    def _fetch_remote_async(self):
        """Fetch the remote plugin list off the GUI thread, then merge it in."""
        def _work():
            try:
                data = self.app.get_plugin_manager().get_available_plugins()
            except Exception:
                data = []
            try:
                self.app.after(0, lambda: self._on_remote_loaded(data))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _on_remote_loaded(self, remote):
        """Merge freshly-fetched remote plugins into the Store (GUI thread)."""
        self._remote_done = True
        if not remote:
            return  # don't cache failures; next visit retries
        self._remote_cache = remote

        if not getattr(self, "_flow", None):
            return  # screen torn down while fetching

        try:
            new_list = self._build_plugin_list(remote)
        except Exception:
            return
        if [p.id for p in new_list] == [
            p.id for p in getattr(self, "_store_plugins", [])
        ]:
            return  # nothing new to show

        self._store_plugins = new_list
        self._rebuild_grid()

    def _rebuild_grid(self):
        """Tear down and re-add every card from self._store_plugins."""
        if not getattr(self, "_flow", None):
            return
        for cid, card in list(self.plugin_cards.items()):
            card.setParent(None)
            card.deleteLater()
        self.plugin_cards = {}
        # Drop any stale items left in the flow layout.
        while self._flow.count():
            item = self._flow.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for p in self._store_plugins:
            self._add_card(p)
        self._grid_host.updateGeometry()

    # ===================================================================
    #  Store action buttons (Info + Install/Uninstall + inline confirm)
    # ===================================================================
    def _inject_store_buttons(self, card: _StoreCard, p):
        is_remote = isinstance(p, RemotePluginWrapper)
        is_uninstalled = getattr(p, "status", None) == "Uninstalled"

        def show_normal_buttons():
            card.clear_buttons()

            info = QPushButton("Info")
            info.setCursor(Qt.CursorShape.PointingHandCursor)
            info.setStyleSheet(_INFO_STYLE)
            info.clicked.connect(
                lambda: self.show_remote_info(p) if is_remote
                else self._show_local_info(p))
            card.button_row.addWidget(info, 1)

            if is_remote or is_uninstalled:
                install = QPushButton("Install")
                install.setCursor(Qt.CursorShape.PointingHandCursor)
                install.setStyleSheet(_INSTALL_STYLE)
                install.clicked.connect(lambda: self.handle_install(p))
                card.button_row.addWidget(install, 1)
            elif getattr(p, "uninstall_enabled", True):
                uninstall = QPushButton("Uninstall")
                uninstall.setCursor(Qt.CursorShape.PointingHandCursor)
                uninstall.setStyleSheet(_UNINSTALL_STYLE)
                uninstall.clicked.connect(show_confirm_buttons)
                card.button_row.addWidget(uninstall, 1)

        def show_confirm_buttons():
            card.clear_buttons()
            cancel = QPushButton("Cancel")
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.setStyleSheet(_CANCEL_STYLE)
            cancel.clicked.connect(show_normal_buttons)
            card.button_row.addWidget(cancel, 1)

            confirm = QPushButton("Confirm")
            confirm.setCursor(Qt.CursorShape.PointingHandCursor)
            confirm.setStyleSheet(_UNINSTALL_STYLE)
            confirm.clicked.connect(confirm_uninstall)
            card.button_row.addWidget(confirm, 1)

        def confirm_uninstall():
            try:
                result = p.uninstall()
            except Exception as e:
                self.app.show_notification(str(e), type="error")
                show_normal_buttons()
                return

            # plugin.uninstall() -> uninstall_plugin() returns (bool, msg).
            if isinstance(result, tuple):
                success, msg = result
            else:
                success, msg = False, str(result)

            if success:
                self.app.show_notification(msg, type="info")
                new_obj = p
                if p.id in getattr(self, "remote_data_map", {}):
                    try:
                        new_obj = RemotePluginWrapper(
                            self.app, self.remote_data_map[p.id])
                    except Exception:
                        p.status = "Uninstalled"
                        new_obj = p
                else:
                    p.status = "Uninstalled"
                self._replace_card(p.id, new_obj)
                try:
                    self.app.refresh_navigation()
                except Exception:
                    pass
            else:
                self.app.show_notification(msg, type="error")
                show_normal_buttons()

        show_normal_buttons()

    def _replace_card(self, old_plugin_id, new_plugin):
        """Swap one card in-place for a fresh one (e.g. after install/uninstall)."""
        for i, p in enumerate(getattr(self, "_store_plugins", [])):
            if p.id == old_plugin_id:
                self._store_plugins[i] = new_plugin
                break
        self._rebuild_grid()

    # ===================================================================
    #  Install / info
    # ===================================================================
    def handle_install(self, remote_plugin):
        from utils.logger import logger

        def on_success(new_plugin_obj, msg):
            try:
                self.app.refresh_navigation()
            except Exception:
                pass
            self.app.show_notification(msg, type="info")

        try:
            url = getattr(remote_plugin, "url", None)
            if not url:
                self.app.show_notification(
                    f"Cannot install {remote_plugin.get_name()}: "
                    "remote source unknown.", type="error")
                return
            success, message = self.app.get_plugin_manager().download_plugin(
                url, remote_plugin.id, remote_plugin.get_name())
        except Exception as e:
            logger.error(f"Store: install failed for "
                         f"{getattr(remote_plugin, 'id', '?')}: {e}")
            self.app.show_notification(f"Install failed: {e}", type="error")
            return

        logger.info(f"Store: Installation result for "
                    f"{remote_plugin.get_name()}: success={success}, "
                    f"msg={message}")
        if success:
            on_success(remote_plugin, message)
        else:
            self.app.show_notification(message, type="error")

    def _show_local_info(self, p):
        try:
            from gui.dialogs import show_info
            show_info(self.app, p.get_name(), p.get_description())
        except Exception:
            self.app.show_notification(p.get_description(), type="info")

    def show_remote_info(self, remote_plugin):
        try:
            from gui.dialogs import show_info
            show_info(self.app, remote_plugin.get_name(),
                      remote_plugin.get_description())
        except Exception:
            self.app.show_notification(
                remote_plugin.get_description(), type="info")


class RemotePluginWrapper:
    """Make a remote plugin dict look like a BasePlugin for the Store card."""

    status_map = BasePlugin.status_map

    def __init__(self, app, data):
        self.app = app
        self.id = data["id"]
        self.name = data["name"]
        self.description = data["description"]
        self.url = data["url"]
        self.order = data.get("order", 99)
        self.status = "Available"
        self.uninstall_enabled = False

    def get_name(self):
        return self.name

    def get_description(self):
        return self.description

    def get_status(self):
        return self.status

    def uninstall(self):
        return False, "Plugin is not installed."

    def get_icon_pixmap(self, size: int = 48) -> QPixmap:
        # Remote plugins use the generic Store icon. icon_light holds the dark
        # glyph and icon_dark the light one, mirroring base_plugin's pairing.
        path = (os.path.join(_DIR, "store_dark.png") if theme.is_dark()
                else os.path.join(_DIR, "store_light.png"))
        if path and os.path.isfile(path):
            return QPixmap(path).scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return QPixmap()
