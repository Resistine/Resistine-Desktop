## @file main.py
## @namespace main
"""Entry point for the Resistine AI EndPoint application (PyQt6).

Author: Petr, Javier, Jackie and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import argparse
import os
import signal
import sys

from PyQt6.QtWidgets import QApplication

from utils import functions as functions
from utils import settings
from utils.logger import logger, setup_logging

DEBUG = False



def _set_resolution_scaling() -> None:
    """Pre-flight check to scale the Qt app based on screen resolution.
    Runs a fast subprocess to read QApplication.primaryScreen() before the main app
    is instantiated, setting QT_SCALE_FACTOR if needed.
    """
    import subprocess
    try:
        # We use a subprocess because QT_SCALE_FACTOR must be set before QApplication,
        # but we need QApplication to read the logical screen size.
        code = (
            "from PyQt6.QtWidgets import QApplication; import sys; "
            "app = QApplication(sys.argv); s = app.primaryScreen().geometry(); "
            "print(f'{s.width()},{s.height()}')"
        )
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        output = subprocess.check_output(
            [sys.executable, "-c", code],
            creationflags=flags,
            stderr=subprocess.DEVNULL
        ).decode().strip()
        
        w_str, h_str = output.split(",")
        w, h = int(w_str), int(h_str)
        
        # 1920x1080 is the 1.0x baseline
        raw_scale = min(w / 1920.0, h / 1080.0)
        
        # Soften the scaling by interpolating halfway to the 1.0 baseline
        scale = 1.0 + (raw_scale - 1.0) * 0.5
        
        # Clamp scale between 0.5x and 2.0x to prevent unusable extremes
        scale = max(0.5, min(scale, 2.0))
        
        # Only set if it deviates significantly from 1.0
        if abs(scale - 1.0) > 0.05:
            os.environ["QT_SCALE_FACTOR"] = f"{scale:.3f}"
    except Exception as e:
        logger.debug(f"Failed to auto-scale resolution: {e}")


def _build_app() -> tuple[QApplication, object]:
    """Create the QApplication + main window and wire startup services."""
    _set_resolution_scaling()
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Resistine")
    qt_app.setApplicationDisplayName("Resistine")
    # Drives the GNOME dock-tile/.desktop association on Linux (parallels the
    # WM_CLASS approach the CTk app used). Harmless elsewhere.
    qt_app.setDesktopFileName("resistine")

    from gui.app_window import AppWindow

    window = AppWindow(qt_app)

    if settings.get("auth", "logged_in", False):
        logger.info("✅ User already logged in.")
        window.create_dashboard()
        if sys.platform == "darwin":
            _resume_macos_installs()
    else:
        logger.info("🔐 Showing login screen…")
        window.show_login()

    try:
        from utils import notifications
        notifications.init()
    except Exception as e:
        logger.warning(f"Failed to initialize system notifications: {e}")

    try:
        from utils.linux_desktop import ensure_desktop_entry
        ensure_desktop_entry()
    except Exception as e:
        logger.debug(f"Desktop entry setup skipped: {e}")

    try:
        from utils import updates
        updates.init(window)
    except Exception as e:
        logger.warning(f"Failed to start auto-updater: {e}")

    return qt_app, window


def _resume_macos_installs() -> None:
    import threading
    try:
        from plugins.wazuh.agent.installer_service import check_and_advance
        threading.Thread(target=check_and_advance, daemon=True).start()
    except Exception:
        pass
    try:
        from plugins.antivirus.installer_service import (
            check_and_advance as av_advance,
        )
        threading.Thread(target=av_advance, daemon=True).start()
    except Exception:
        pass


def main() -> int:
    global DEBUG

    parser = argparse.ArgumentParser(
        description="Resistine Desktop Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug mode")
    parser.add_argument("-l", "--log-level",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        default="INFO", help="Set logging level (default: INFO)")
    args = parser.parse_args()

    if args.debug or functions.is_running_in_ide():
        DEBUG = True

    log_level = args.log_level
    if DEBUG and log_level == "INFO" and not any(
        a in sys.argv for a in ["-l", "--log-level"]
    ):
        log_level = "DEBUG"
    setup_logging(level=log_level)

    qt_app, window = _build_app()

    if DEBUG:
        logger.info("Debug mode enabled")
        logger.info(f"Platform: {sys.platform}")
        logger.info(f"Python version: {sys.version}")

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    window.show()
    window.raise_()
    window.activateWindow()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
