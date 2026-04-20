"""ClamAV platform module — Windows (stub with safe defaults).

Functions return safe no-op defaults so the antivirus UI can render
and be developed without a working ClamAV backend.
See clamav_platform_darwin.py for a working reference implementation.

IMPORTANT: ClamAV on Windows uses TCP sockets (127.0.0.1:3310) instead
of Unix sockets. The _ping_socket and _contscan_socket functions in
clamav_common.py use AF_UNIX — they need a TCP branch for Windows.
This is documented in clamav_common.py as a known complication.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import shutil

from utils.logger import logger


# ── Platform interface ────────────────────────────────────


def system_db_dir() -> str | None:
    """Return system DB dir path if it exists, else None."""
    return None


def system_db_dir_writable() -> str | None:
    """Return system DB dir if writable by the current user, else None."""
    return None


def system_clamd_socket_path() -> str:
    """Return the clamd connection address.

    Windows ClamAV uses TCP, not Unix sockets.
    """
    return "127.0.0.1:3310"


def system_clamd_conf_path() -> str:
    """Return the system-level clamd.conf location."""
    candidates = [
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "ClamAV", "clamd.conf",
        ),
        os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"),
            "ClamAV", "clamd.conf",
        ),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def find_binary(name: str) -> str | None:
    """Find a ClamAV binary on Windows via PATH lookup."""
    # shutil.which appends .exe automatically on Windows
    return shutil.which(name)


def find_certs_dir() -> str | None:
    """Locate the ClamAV CVD signature-verification certs directory."""
    candidates = [
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "ClamAV", "certs",
        ),
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "Resistine", "ClamAV", "certs",
        ),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def clamav_env() -> dict[str, str]:
    """Return env dict for ClamAV on Windows."""
    env = {**os.environ}
    certs = find_certs_dir()
    if certs:
        env["CVD_CERTS_DIR"] = certs
    return env


def is_app_bundle() -> bool:
    """Return False — packaged install detection not yet implemented."""
    return False


def daemons_approved() -> bool:
    """Return True (dev mode — no service approval needed)."""
    return True


def has_full_disk_access() -> bool:
    """Return True (dev mode — no permission check needed)."""
    return True


def open_fda_settings():
    """No-op on Windows — no equivalent to macOS Full Disk Access."""
    logger.info(
        "Antivirus: on Windows, run Resistine as Administrator "
        "for real-time protection.",
    )


def open_login_items_settings():
    """No-op on Windows — no equivalent to macOS Login Items."""
    logger.info(
        "Antivirus: use services.msc to manage the ClamAV Windows service.",
    )


def ensure_daemons_registered():
    """No-op — Windows service registration not yet implemented."""
    logger.debug("Antivirus: daemon registration not yet implemented on Windows")


def activate_system_daemons() -> tuple[bool, str]:
    """Not yet implemented on Windows."""
    return False, "System daemon activation is not yet implemented on Windows."


def deactivate_system_daemons() -> tuple[bool, str]:
    """Not yet implemented on Windows."""
    return False, "System daemon deactivation is not yet implemented on Windows."


def is_clamonacc_running() -> bool:
    """Return False — real-time protection check not yet implemented."""
    return False
