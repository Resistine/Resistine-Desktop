"""Linux system notifications — notify-send (libnotify) backend.

Uses notify-send (from libnotify-bin) to deliver desktop notifications
via the org.freedesktop.Notifications D-Bus service. If notify-send is
not installed, sends are silently skipped (logged at debug).
"""

import shutil
import subprocess

from utils.logger import logger

_NOTIFY_SEND = shutil.which("notify-send")


def init():
    if _NOTIFY_SEND is None:
        logger.debug("Linux notifications: notify-send not found on PATH")
    else:
        logger.debug("Linux notifications: using %s", _NOTIFY_SEND)


def send(title: str, body: str, urgency: str = "normal"):
    if not _NOTIFY_SEND:
        logger.debug("notify-send not found; Linux notification skipped")
        return
    try:
        subprocess.Popen(
            [
                _NOTIFY_SEND,
                "--app-name=Resistine",
                f"--urgency={urgency}",
                title,
                body,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as e:
        logger.debug(f"notify-send failed: {e}")
