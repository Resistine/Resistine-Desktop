## @file main.py
## @namespace plugins.template
"""Template plugin (PyQt6) — the canonical starting point for a new plugin.

Copy this whole ``plugins/template/`` folder to ``plugins/<yourname>/`` and:

  1. Rename the icons (``template_light.png`` / ``template_dark.png``) — they
     are monochrome line art; the shell tints the strokes to the theme, so only
     the *shape* matters (see ``base_plugin.BasePlugin._tint``).
  2. Give the plugin a unique ``id`` and a real ``order`` (see below).
  3. Build your UI in ``create_main_screen`` and return a QWidget.

Discovery is automatic: ``plugin_manager.load_plugins`` scans ``plugins/`` (and
the user plugins dir), imports each folder's ``main.py``, and instantiates its
``Plugin`` class. No manifest, no registration — the folder *is* the plugin.

This template ships with ``order=-1`` so it stays INVISIBLE in the running app
(the sidebar skips ``order <= 0`` — see ``gui/app_window.py``) while remaining a
live, copy-me example in the repo. Your real plugin wants a positive order:
plugins sort by it, and user-installed plugins land between Store (1000) and
Help (1010).

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from gui.qt_widgets import heading, muted, scroll_page
from plugins.base_plugin import BasePlugin

_DIR = os.path.dirname(os.path.realpath(__file__))


class Plugin(BasePlugin):
    """A minimal plugin. Every plugin subclasses BasePlugin and overrides
    ``create_main_screen`` — that is the entire required contract."""

    def __init__(self, app):
        super().__init__(
            # A unique string id. Core/bundled ids are 001–012; the remote demo
            # plugins use 000 (Template) and 100 (Calculator). Pick your own.
            id="000",
            version="2025.01.01",
            # Sidebar sort key. -1 (or <= 0) hides the plugin from the sidebar;
            # give your plugin a positive order to make it appear.
            order=-1,
            name="Template",
            # None => no status badge. Return a status_map key ("ok", "warning",
            # "error", ...) from check_status() to show one.
            status=None,
            description="A template plugin that demonstrates the plugin structure.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Template", "ES": "Plantilla", "FR": "Modèle"},
            icon_light_path=os.path.join(_DIR, "template_light.png"),
            icon_dark_path=os.path.join(_DIR, "template_dark.png"),
            # False => no Uninstall button in the Store (use for core plugins).
            uninstall_enabled=True,
        )
        # The host AppWindow is injected by the manager; keep a handle for
        # navigation, the plugin manager, after()-style callbacks, etc.
        self.app = app

    def create_main_screen(self) -> QWidget:
        """Build and return this plugin's screen. Called on first navigation.

        Wrap content in ``scroll_page`` so it scrolls when the window is short;
        use the shared ``heading`` / ``muted`` helpers so text inherits the
        app-wide font and recolours automatically on light/dark toggle.
        """
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(24, 24, 24, 24)
        col.setSpacing(8)

        col.addWidget(heading("Template"))
        col.addWidget(
            muted(
                "This is a template plugin. Copy plugins/template/ to a new "
                "folder, change the id/order/name, and build your UI here."
            )
        )
        col.addStretch(1)

        return scroll_page(inner)
