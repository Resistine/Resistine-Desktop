## @file plugins/settings/main.py
## @namespace settings_plugin
"""Settings plugin (PyQt6) — faithful port of the CTk layout.

Five full-width cards, each a "section title + divider" header over its content,
in the original order: Profile, API key, Appearance, Software Updates, Uninstall.

Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import glob
import os
import sys

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.qt_widgets import scroll_page
from plugins.base_plugin import BasePlugin
from utils import settings
from utils.i18n import get_text
from utils.logger import logger

_DIR = os.path.dirname(os.path.realpath(__file__))
_DEFAULT_BASE = "https://dashboard.resisti.net:8002/v1"


def _t(key, fallback):
    try:
        val = get_text(key)
        return val if val and val != key else fallback
    except Exception:
        return fallback


class Plugin(BasePlugin):
    """Settings plugin."""

    def __init__(self, app):
        super().__init__(
            id="010", version="2025.01.01", order=1020, name="Settings",
            status=None,
            description="This plugin allows you to configure your account settings.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Settings", "ES": "Configuracion",
                          "FR": "Paramètres"},
            icon_light_path=os.path.join(_DIR, "settings_light.png"),
            icon_dark_path=os.path.join(_DIR, "settings_dark.png"),
            uninstall_enabled=False,
        )
        self.app = app

    # ---- A card with a section-title + divider header ---------------------
    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Surface")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 16px; font-weight: 700;")
        lay.addWidget(lbl)
        div = QFrame()
        div.setFixedHeight(1)
        div.setObjectName("Divider")
        lay.addWidget(div)
        lay.addSpacing(4)
        return card, lay

    def _muted(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {theme.color('text_secondary')};")
        return lbl

    def create_main_screen(self):
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(20, 16, 20, 20)
        col.setSpacing(12)

        col.addWidget(self._profile_card())
        col.addWidget(self._api_card())
        col.addWidget(self._appearance_card())
        col.addWidget(self._updates_card())
        col.addWidget(self._uninstall_card())
        col.addStretch(1)
        return scroll_page(inner)

    # ---- Profile ----------------------------------------------------------
    def _profile_card(self) -> QWidget:
        card, lay = self._card("Profile")
        # Button text/color/action mirrors auth state: logged in -> Log Out
        # (red, destructive); logged out -> Log In (primary blue, action).
        logged_in = settings.get("auth", "logged_in", False)
        email = settings.get("auth", "email", None)
        lay.addWidget(self._muted(
            f"Email: {email}" if email else "Not signed in"))

        if logged_in:
            self.logout_button = QPushButton("Log Out")
            self.logout_button.setStyleSheet(
                "background-color: #DC3545; color: white; border: none;"
                "border-radius: 8px; padding: 8px 16px; font-weight: 600;")
            # Sign-out icon only shown when logged in. The button is red with
            # white text in BOTH themes, so the icon must always be the light
            # glyph (signout_dark.png) to match that white text — picking by
            # app theme gave a dark, low-contrast glyph in light mode and never
            # updated on a theme toggle.
            p = os.path.join(_DIR, "signout_dark.png")
            if os.path.isfile(p):
                self.logout_button.setIcon(QIcon(p))
                self.logout_button.setIconSize(QSize(18, 18))
            self.logout_button.clicked.connect(self._handle_logout)
        else:
            self.logout_button = QPushButton("Log In")
            self.logout_button.setStyleSheet(
                "background-color: #0D5394; color: white; border: none;"
                "border-radius: 8px; padding: 8px 16px; font-weight: 600;")
            self.logout_button.clicked.connect(self._handle_login)
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.logout_button, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    # ---- API key ----------------------------------------------------------
    def _api_card(self) -> QWidget:
        card, lay = self._card(_t("settings.apikey.label", "OpenAI API Key"))

        self.api_key_entry = QLineEdit()
        self.api_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_entry.setPlaceholderText(
            _t("settings.apikey.placeholder", "Enter your API key"))
        existing_key = settings.get_secret("chat", "openai_api_key")
        if existing_key:
            self.api_key_entry.setText(existing_key)
        lay.addWidget(self.api_key_entry)

        lay.addWidget(self._muted(_t("settings.apibase.label", "API Base URL")))
        self.api_base_entry = QLineEdit()
        self.api_base_entry.setPlaceholderText(
            _t("settings.apibase.placeholder", "API base URL"))
        self.api_base_entry.setText(
            settings.get("chat", "openai_base_url") or _DEFAULT_BASE)
        lay.addWidget(self.api_base_entry)

        self.disable_animation_checkbox = QCheckBox(
            _t("settings.chat.disable_animation", "Disable typing animation"))
        self.disable_animation_checkbox.setChecked(
            bool(settings.get("chat", "disable_animation", False)))
        self.disable_animation_checkbox.toggled.connect(
            self.save_animation_setting)
        lay.addWidget(self.disable_animation_checkbox)

        row = QHBoxLayout()
        save = QPushButton(_t("settings.apikey.save", "Save"))
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self.save_api_key)
        row.addWidget(save)
        self.status_label = QLabel("")
        row.addWidget(self.status_label, 1)
        lay.addLayout(row)
        return card

    # ---- Appearance -------------------------------------------------------
    def _appearance_card(self) -> QWidget:
        card, lay = self._card("Appearance")
        lay.addWidget(self._muted("Mode:"))
        self.appearance_combo = QComboBox()
        self.appearance_combo.addItems(["System", "Light", "Dark"])
        self.appearance_combo.setCurrentText(
            settings.get("ui", "appearance_mode", "System"))
        self.appearance_combo.currentTextChanged.connect(
            self.change_appearance_mode)
        lay.addWidget(self.appearance_combo)
        return card

    # ---- Software Updates -------------------------------------------------
    def _updates_card(self) -> QWidget:
        card, lay = self._card("Software Updates")
        lay.addWidget(self._muted(f"Current version: {self._get_app_version()}"))
        check = QPushButton("Check for Updates")
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.clicked.connect(self._check_for_updates)
        lay.addWidget(check, 0, Qt.AlignmentFlag.AlignLeft)
        self.update_status_label = QLabel("")
        lay.addWidget(self.update_status_label)
        return card

    # ---- Uninstall --------------------------------------------------------
    def _uninstall_card(self) -> QWidget:
        card, lay = self._card("Uninstall")
        lay.addWidget(self._muted(
            "Permanently remove Resistine and all associated data from this "
            "computer."))
        self.uninstall_button = QPushButton("Uninstall Resistine")
        self.uninstall_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_button.setStyleSheet(
            "background-color: #DC3545; color: white; border: none;"
            "border-radius: 8px; padding: 8px 16px; font-weight: 600;")
        self.uninstall_button.clicked.connect(self._handle_uninstall)
        lay.addWidget(self.uninstall_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.uninstall_status_label = QLabel("")
        lay.addWidget(self.uninstall_status_label)
        return card

    # ===================================================================
    #  Actions
    # ===================================================================
    def save_animation_setting(self):
        settings.set("chat", "disable_animation",
                     self.disable_animation_checkbox.isChecked())

    def save_api_key(self):
        api_key = self.api_key_entry.text().strip()
        api_base = self.api_base_entry.text().strip()
        if not api_key and not api_base:
            return
        ok_key = (settings.set_secret("chat", "openai_api_key", api_key)
                  if api_key else True)
        ok_base = settings.set("chat", "openai_base_url",
                               api_base if api_base else None)
        if ok_key and ok_base:
            self.status_label.setText(
                _t("settings.apikey.saved_success", "Saved"))
            self.status_label.setStyleSheet("color: #16A34A;")
            for plugin in getattr(self.app, "plugin_list", []):
                if plugin.get_name() == "Chat" and hasattr(
                        plugin, "reinitialize_client"):
                    plugin.reinitialize_client()
                    break
            self.app.after(2500, lambda: self.status_label.setText(""))
        else:
            self.status_label.setText(
                _t("settings.apikey.saved_error", "Save failed"))
            self.status_label.setStyleSheet("color: #DC2626;")

    def change_appearance_mode(self, new_mode: str):
        settings.set("ui", "appearance_mode", new_mode)
        try:
            self.app.set_appearance_mode(new_mode)
        except Exception as e:
            logger.error(f"Theme switch failed: {e}")

    def _check_for_updates(self):
        try:
            from utils import updates
            if not updates.is_available():
                self.update_status_label.setText(
                    "Updates not available in this build")
                self.app.after(
                    5000, lambda: self.update_status_label.setText(""))
                return
            self.update_status_label.setText("Checking for updates…")
            result = updates.check_for_updates()
            if result == "error":
                self.update_status_label.setText("Update check failed")
            self.app.after(4000, lambda: self.update_status_label.setText(""))
        except Exception as e:
            logger.error(f"Update check error: {e}")
            self.update_status_label.setText(f"Error: {e}")

    def _get_app_version(self):
        try:
            if getattr(sys, "frozen", False):
                import plistlib
                contents_dir = os.path.dirname(os.path.dirname(sys.executable))
                plist_path = os.path.join(contents_dir, "Info.plist")
                if os.path.exists(plist_path):
                    with open(plist_path, "rb") as f:
                        info = plistlib.load(f)
                    return info.get("CFBundleShortVersionString", "1.0.0")
        except Exception:
            pass
        try:
            from utils.updates.version import get_current_version
            version = get_current_version()
            if version != "0.0.0":
                return version
        except Exception:
            pass
        return "1.0.0"

    def _handle_uninstall(self):
        confirmed = QMessageBox.question(
            self.app, "Uninstall Resistine",
            "Are you sure you want to completely uninstall Resistine?\n\n"
            "This will remove all VPN configurations, application data, and the "
            "application itself.\n\nThis action cannot be undone.",
        ) == QMessageBox.StandardButton.Yes
        if not confirmed:
            return
        self.uninstall_button.setEnabled(False)
        self.uninstall_status_label.setText("Uninstalling…")
        try:
            from utils import uninstall

            def _progress(msg):
                self.uninstall_status_label.setText(msg)

            success, message = uninstall.run_uninstall(
                self.app, progress_callback=_progress)
            if success:
                self.uninstall_status_label.setText("Uninstalled. Closing…")
                if sys.platform == "darwin":
                    # macOS: deferred hard-exit so teardown finishes flushing
                    # (the spawned uninstaller outlives us).
                    import os as _os
                    import threading as _th
                    self.app.close()
                    _th.Timer(0.3, lambda: _os._exit(0)).start()
                else:
                    # Windows/Linux: orderly shutdown so any spawned
                    # uninstaller (Inno's unins000.exe) and WinSparkle
                    # finish cleanly. Quit the Qt loop; main()'s teardown
                    # (updates.shutdown + hard exit) runs after exec()
                    # returns.
                    from PyQt6.QtWidgets import QApplication
                    self.app.close()
                    QApplication.instance().quit()
            else:
                self.uninstall_button.setEnabled(True)
                self.uninstall_status_label.setText(message)
        except Exception as e:
            logger.error(f"Uninstall error: {e}")
            self.uninstall_button.setEnabled(True)
            self.uninstall_status_label.setText(f"Error: {e}")

    def _login_plugin_installed(self) -> bool:
        """True if the Login plugin (id 007) is installed."""
        return any(
            getattr(p, "id", None) == "007"
            for p in getattr(self.app, "plugins", None)
            or getattr(self.app, "plugin_list", [])
            or []
        )

    def _handle_logout(self):
        # Without the Login plugin installed there's no way to sign back in,
        # so refuse the logout up-front rather than stranding the user on a
        # broken bootstrap path.
        if not self._login_plugin_installed():
            self.app.show_notification(
                "Please install the Login plugin from the Store first.",
                type="warning",
            )
            return
        confirmed = QMessageBox.question(
            self.app, "Log Out",
            "Are you sure you want to log out?\n\nThis will sign you out and "
            "remove your VPN configurations, security agent enrollment, chat "
            "history, and account data from this device.\n\nAn administrator "
            "password may be required to fully uninstall the Wazuh agent.",
        ) == QMessageBox.StandardButton.Yes
        if not confirmed:
            return
        self._disconnect_vpn()
        self._remove_wazuh_agent()
        self._clear_user_data()
        try:
            self.app.show_login()
        except Exception as e:
            logger.error(f"Failed to show login screen: {e}")
            self.app.show_notification(f"Logout failed: {e}", type="error")

    def _handle_login(self):
        """Bring up the full-screen login. No data is cleared — auth namespace
        was already clean (user is logged out / skipped). Guarded the same
        way as logout: if the Login plugin was uninstalled, ask the user to
        reinstall it before continuing.
        """
        if not self._login_plugin_installed():
            self.app.show_notification(
                "Please install the Login plugin from the Store first.",
                type="warning",
            )
            return
        try:
            self.app.show_login()
        except Exception as e:
            logger.error(f"Failed to show login screen: {e}")
            self.app.show_notification(
                f"Could not open sign-in: {e}", type="error")

    # ===================================================================
    #  Logout cleanup helpers (framework-agnostic — kept from CTk version)
    # ===================================================================
    def _disconnect_vpn(self):
        import platform as plat
        try:
            system = plat.system()
            if system == "Darwin":
                from plugins.vpn.config_manager import VPNConfigManager
                from plugins.vpn.wireguard.vpn_functions_darwin import (
                    get_writable_wireguard_dir, stop_vpn,
                )
                mgr = VPNConfigManager(get_writable_wireguard_dir())
                stop_vpn(mgr.get_active_config_path() or "")
            elif system == "Windows":
                from plugins.vpn.wireguard.vpn_windows_client import disconnect
                disconnect("resistine")
            elif system == "Linux":
                from plugins.vpn.config_manager import VPNConfigManager
                from plugins.vpn.wireguard.vpn_functions_linux import (
                    get_writable_wireguard_dir, stop_vpn,
                )
                mgr = VPNConfigManager(get_writable_wireguard_dir())
                path = mgr.get_active_config_path()
                if path:
                    stop_vpn(path)
        except Exception as e:
            logger.warning(f"VPN disconnect on logout failed: {e}")

    def _remove_wazuh_agent(self):
        import platform as plat
        try:
            system = plat.system()
            if system == "Darwin":
                from plugins.wazuh.agent.wazuh_functions_darwin import remove_agent
            elif system == "Windows":
                from plugins.wazuh.agent.wazuh_functions_windows import remove_agent
            elif system == "Linux":
                from plugins.wazuh.agent.wazuh_functions_linux import remove_agent
            else:
                return
            if not remove_agent(wipe_keys=True):
                logger.warning("Wazuh agent removal reported failure")
        except Exception as e:
            logger.warning(f"Wazuh agent removal on logout failed: {e}")

    def _clear_user_data(self):
        import platform as plat
        settings.clear_namespace("auth")
        settings.delete("wireguard", "private_key")
        settings.delete("wireguard", "public_key")
        settings.clear_namespace("vpn")
        try:
            system = plat.system()
            if system == "Darwin":
                from plugins.vpn.wireguard.vpn_functions_darwin import (
                    get_writable_wireguard_dir,
                )
            elif system == "Windows":
                from plugins.vpn.wireguard.vpn_functions_windows import (
                    get_writable_wireguard_dir,
                )
            else:
                from plugins.vpn.wireguard.vpn_functions_linux import (
                    get_writable_wireguard_dir,
                )
            wg_dir = get_writable_wireguard_dir()
            for conf in glob.glob(os.path.join(wg_dir, "*.conf")):
                try:
                    os.remove(conf)
                except OSError as e:
                    logger.warning(f"Failed to remove VPN config {conf}: {e}")
        except Exception as e:
            logger.warning(f"VPN config cleanup failed: {e}")
        settings.clear_namespace("chat_history")
        settings.delete("chat", "openai_api_key")
        settings.delete("chat", "openai_base_url")
        settings.clear_namespace("wazuh")
