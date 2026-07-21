# -*- coding: utf-8 -*-
# @file plugins/login/main.py
# @namespace plugins.login.main
# Description: Login plugin (PyQt6) — email + OTP authentication.
# Author: Sherwin and the Resistine Team
# Copyright: Resistine (c) 2025
# Licensed under the GNU General Public License v2 or later

import os
import platform
import re
import threading
import webbrowser

from PyQt6.QtCore import QRegularExpression, Qt
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plugins.base_plugin import BasePlugin
from plugins.login.api import LoginAPI
from utils.functions import get_resource_path
from utils.logger import logger

_SIGNUP_URL = "https://resistine-main2-v3-34632416.dev.odoo.com/"

if platform.system() == "Windows":
    from plugins.vpn.wireguard.vpn_functions_windows import (
        save_vpn_configuration, setup_vpn_keys,
    )
elif platform.system() == "Linux":
    from plugins.vpn.wireguard.vpn_functions_linux import (
        save_vpn_configuration, setup_vpn_keys,
    )
elif platform.system() == "Darwin":
    from plugins.vpn.wireguard.vpn_functions_darwin import (
        save_vpn_configuration, setup_vpn_keys,
    )
else:  # pragma: no cover
    def setup_vpn_keys():
        return None

    def save_vpn_configuration(config_data, config_name="resistine"):
        return None


class Plugin(BasePlugin):
    def __init__(self, app):
        super().__init__(
            id="007", version="2025.01.01", order=0, name="Login",
            status=None, description="Login to the Resistine application.",
            supported_systems=["Windows", "Linux", "Mac"],
            translations={"US": "Login", "ES": "Acceso", "FR": "Connexion"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "login_light.png"),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "login_dark.png"),
        )
        self.app = app
        self.email = None
        self.api = LoginAPI("https://validate.resistine.work")

    def show(self):
        self.app.setCentralWidget(self.create_main_screen())

    def create_main_screen(self):
        from gui.qt_widgets import pixmap

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 20, 40, 16)
        outer.addStretch(1)

        col = QWidget()
        col.setMaximumWidth(440)
        v = QVBoxLayout(col)
        v.setSpacing(18)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        shield = QLabel()
        shield.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = pixmap(get_resource_path(
            os.path.join("resources", "icons", "ResistineShield.png")), 250)
        if not pm.isNull():
            shield.setPixmap(pm)
        v.addWidget(shield)

        self.title_label = QLabel(
            "Sign in with your Resistine account to get started.")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 16px;")
        v.addWidget(self.title_label)

        self.email_entry = QLineEdit()
        self.email_entry.setPlaceholderText("Enter your email address")
        self.email_entry.setFixedWidth(400)
        self.email_entry.setMinimumHeight(45)
        self.email_entry.returnPressed.connect(self.handle_signin_click)
        v.addWidget(self.email_entry, 0, Qt.AlignmentFlag.AlignHCenter)

        self.otp_entry = QLineEdit()
        self.otp_entry.setPlaceholderText("Enter OTP")
        self.otp_entry.setEchoMode(QLineEdit.EchoMode.Password)
        # Digits only + clamp to OTP length, so pastes like "123 456" or
        # "123-456" reduce to the code instead of failing validation.
        self.otp_entry.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\d*")))
        self.otp_entry.setMaxLength(6)
        self.otp_entry.setFixedWidth(400)
        self.otp_entry.setMinimumHeight(45)
        self.otp_entry.returnPressed.connect(self.verify_otp)
        self.otp_entry.hide()
        v.addWidget(self.otp_entry, 0, Qt.AlignmentFlag.AlignHCenter)

        self.primary_btn = QPushButton("Sign in")
        self.primary_btn.setFixedWidth(400)
        self.primary_btn.setMinimumHeight(45)
        self.primary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_btn.clicked.connect(self.handle_signin_click)
        v.addWidget(self.primary_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.secondary_btn = QPushButton("Create new account")
        self.secondary_btn.setObjectName("Link")
        self.secondary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.secondary_btn.clicked.connect(lambda: webbrowser.open(_SIGNUP_URL))
        v.addWidget(self.secondary_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status_label)

        outer.addWidget(col, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

        # Footer (privacy + terms), centered.
        privacy = QLabel("Privacy and Cookies")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        privacy.setStyleSheet("color: #0D5394; font-size: 12px;")
        terms = QLabel("By signing in you agree to the Terms of Use")
        terms.setAlignment(Qt.AlignmentFlag.AlignCenter)
        terms.setStyleSheet("color: #888888; font-size: 12px;")
        outer.addWidget(privacy)
        outer.addWidget(terms)

        # Skip (bottom-right).
        skip_row = QHBoxLayout()
        skip_row.addStretch(1)
        skip = QPushButton("Skip")
        skip.setObjectName("Secondary")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.clicked.connect(self.skip_login)
        skip_row.addWidget(skip)
        outer.addLayout(skip_row)

        self._otp_mode = False
        return page

    def update_status(self, message, color="red"):
        self.status_label.setText(message or "")
        self.status_label.setStyleSheet(f"color: {color};")

    def handle_signin_click(self):
        if self._otp_mode:
            return
        email = self.email_entry.text().strip()
        regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not email:
            self.update_status("Please enter an email address")
            return
        if not re.match(regex, email):
            self.update_status("Please enter a valid email address")
            return
        self.email = email
        self.update_status("Sending code…", "#16A34A")
        self.primary_btn.setEnabled(False)
        self.primary_btn.setText("Sending…")

        def work():
            try:
                success, message, _ = self.api.send_otp(email)
            except Exception as e:
                success, message = False, str(e)
            self.app.after(0, lambda: self._after_send_otp(success, message))

        threading.Thread(target=work, daemon=True).start()

    def _after_send_otp(self, success, message):
        self.primary_btn.setEnabled(True)
        if success:
            self.update_status(message or "Code sent.", "#16A34A")
            self._enter_otp_mode()
        else:
            self.primary_btn.setText("Sign in")
            self.update_status(message or "Failed to send code.")
            self.app.show_notification(message or "Failed to send code.",
                                       type="error")

    def _enter_otp_mode(self):
        self._otp_mode = True
        self.title_label.setText(f"Enter the 6-digit code sent to {self.email}")
        self.email_entry.hide()
        self.otp_entry.show()
        self.otp_entry.setFocus()
        self.primary_btn.setText("Verify OTP")
        self.primary_btn.clicked.disconnect()
        self.primary_btn.clicked.connect(self.verify_otp)
        self.secondary_btn.setText("Back")
        self.secondary_btn.clicked.disconnect()
        self.secondary_btn.clicked.connect(self._back_to_email)

    def _back_to_email(self):
        self._otp_mode = False
        self.title_label.setText(
            "Sign in with your Resistine account to get started.")
        self.otp_entry.hide()
        self.otp_entry.clear()
        self.email_entry.show()
        self.primary_btn.setText("Sign in")
        self.primary_btn.clicked.disconnect()
        self.primary_btn.clicked.connect(self.handle_signin_click)
        self.secondary_btn.setText("Create new account")
        self.secondary_btn.clicked.disconnect()
        self.secondary_btn.clicked.connect(lambda: webbrowser.open(_SIGNUP_URL))
        self.update_status("")

    def verify_otp(self):
        if not self._otp_mode:
            return
        otp = self.otp_entry.text().strip()
        if not otp:
            self.update_status("Please enter OTP")
            return
        public_key = setup_vpn_keys()
        if not public_key:
            self.update_status("Failed to generate encryption keys")
            return
        self.update_status("Verifying…", "#16A34A")
        self.primary_btn.setEnabled(False)

        def work():
            try:
                success, message, result = self.api.verify_otp(
                    email=self.email, otp=otp, public_key=public_key)
            except Exception as e:
                success, message, result = False, str(e), {}
            self.app.after(
                0, lambda: self._after_verify(success, message, result))

        threading.Thread(target=work, daemon=True).start()

    def _after_verify(self, success, message, result):
        self.primary_btn.setEnabled(True)
        if not success:
            logger.error(f"Login failed: {message}")
            self.update_status(message or "Verification failed")
            self.app.show_notification(message or "Verification failed",
                                       type="error")
            return
        logger.info("Login successful")
        from utils import settings as app_settings
        app_settings.set("auth", "email", self.email)
        self._save_vpn_config(result)
        app_settings.set("auth", "logged_in", True)

        # Start Wazuh download + ClamAV DB pre-seed while public internet is
        # available (VPN DNS cannot resolve packages.wazuh.com).
        if platform.system() == "Darwin":
            try:
                from plugins.wazuh.agent.installer_service import (
                    ensure_download_started,
                )
                threading.Thread(
                    target=ensure_download_started, daemon=True).start()
            except Exception:
                pass
            try:
                from plugins.antivirus.installer_service import (
                    ensure_db_seed_started,
                )
                threading.Thread(
                    target=ensure_db_seed_started, daemon=True).start()
            except Exception:
                pass

        self.app.show_notification("Login successful!", type="info")

        # First login on this machine: run the unified setup wizard instead
        # of dropping the user on the dashboard with everything unconfigured.
        needs_setup = not app_settings.get("setup", "complete", False)
        if needs_setup:
            self._transition_to_setup_wizard()
        else:
            self.app.create_dashboard()

    def _save_vpn_config(self, result):
        keys = ("vpn_config", "data", "vpn_configuration", "wireguard_config")
        config_data = next((result[k] for k in keys if k in (result or {})), None)
        if not config_data:
            logger.warning("No VPN config in API response")
            return
        try:
            config_path = save_vpn_configuration(
                config_data, config_name="resistine")
            if config_path:
                from plugins.vpn.config_manager import (
                    RESISTINE_CONFIG_NAME, VPNConfigManager,
                )
                mgr = VPNConfigManager(os.path.dirname(config_path))
                mgr.register_config(RESISTINE_CONFIG_NAME, source="api")
                mgr.set_active_config(RESISTINE_CONFIG_NAME)
                logger.info("VPN config registered: %s", config_path)
        except Exception as e:
            logger.warning(f"Failed to save VPN config: {e}")

    def skip_login(self):
        logger.info("User skipped login")
        self.app.show_notification(
            "Login skipped — some features may be unavailable", type="warning")
        self.app.create_dashboard()

    def _transition_to_setup_wizard(self):
        """Transition from login to the unified customer setup wizard.

        The wizard guides the user through every permission/installation
        their OS needs (VPN, antivirus, Full Disk Access, endpoint
        monitoring) behind one flow.
        """
        from plugins.login.setup_wizard import SetupWizardScreen

        def on_setup_complete():
            self.app.create_dashboard()

        self._wizard = SetupWizardScreen(self.app, on_setup_complete)
        self._wizard.show()
