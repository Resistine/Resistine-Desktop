"""Linux system notifications via the freedesktop.org Desktop Notifications spec.

Primary path: the ``org.freedesktop.Notifications`` D-Bus service, called over
the session bus with jeepney — a pure-Python D-Bus client we already depend on
(keyring/secretstorage pull it in). This is the cross-desktop standard, so it
works on GNOME/KDE/XFCE/Cinnamon/etc. with whatever notification daemon is
running, with no extra binary and no PyGObject. Falls back to the ``notify-send``
CLI if the bus isn't reachable (e.g. no session bus / headless).

Sending runs on a daemon thread because opening the bus and awaiting the reply
blocks briefly; the macOS backend's send is async, so this keeps parity (never
stalls the caller, which is usually the UI thread).

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import shutil
import subprocess
import threading

from utils.logger import logger

# App urgency level -> freedesktop urgency byte (spec: 0 low, 1 normal, 2 crit).
_URGENCY_BYTE = {"low": 0, "normal": 1, "critical": 2}


def _icon() -> str:
    """Absolute path to the bundled app icon, or a themed-icon name fallback."""
    # utils/notifications/linux.py -> repo root is three dirs up.
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )
    path = os.path.join(root, "resources", "icons", "app_icon.png")
    return path if os.path.isfile(path) else "security-high"


def init():
    """No initialization required on Linux (no authorization step)."""
    return


def _send_via_dbus(title: str, body: str, urgency_byte: int, icon: str) -> bool:
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
    except Exception:
        return False
    try:
        addr = DBusAddress(
            "/org/freedesktop/Notifications",
            bus_name="org.freedesktop.Notifications",
            interface="org.freedesktop.Notifications",
        )
        # Notify(app_name, replaces_id, app_icon, summary, body,
        #        actions, hints, expire_timeout). expire -1 = daemon default;
        #        critical-urgency notifications persist until dismissed.
        msg = new_method_call(
            addr, "Notify", "susssasa{sv}i",
            ("Resistine", 0, icon, title, body, [],
             {"urgency": ("y", urgency_byte)}, -1),
        )
        conn = open_dbus_connection(bus="SESSION")
        try:
            conn.send_and_get_reply(msg)
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.debug("D-Bus notification failed, trying notify-send: %s", e)
        return False


def _send_via_notify_send(title: str, body: str, urgency: str,
                          icon: str) -> bool:
    if shutil.which("notify-send") is None:
        return False
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=Resistine",
             f"--urgency={urgency}", "-i", icon, title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        logger.debug("notify-send notification failed: %s", e)
        return False


def send(title: str, body: str, urgency: str = "normal"):
    """Send a Linux desktop notification. Never raises.

    Args:
        title: Notification title.
        body: Notification body text.
        urgency: One of "low", "normal", "critical".
    """
    urgency_byte = _URGENCY_BYTE.get(urgency, 1)
    icon = _icon()

    def _run():
        if not _send_via_dbus(title, body, urgency_byte, icon):
            _send_via_notify_send(title, body, urgency, icon)

    threading.Thread(target=_run, daemon=True).start()
