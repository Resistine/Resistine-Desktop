"""ClamAV platform module — Linux (stub with safe defaults).

Functions return safe no-op defaults so the antivirus UI can render
and be developed without a working ClamAV backend.
See clamav_platform_darwin.py for a working reference implementation.

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
    """Return the system-level clamd socket path.

    Probes common Linux locations and returns the first that exists,
    or a sensible default.
    """
    candidates = [
        "/var/run/clamav/clamd.ctl",
        "/var/run/clamd.scan/clamd.sock",
        "/var/lib/clamav/clamd.sock",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def system_clamd_conf_path() -> str:
    """Return the system-level clamd.conf location."""
    candidates = [
        "/etc/clamav/clamd.conf",
        "/etc/clamd.d/scan.conf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def find_binary(name: str) -> str | None:
    """Find a ClamAV binary on Linux via PATH lookup."""
    return shutil.which(name)


def find_certs_dir() -> str | None:
    """Locate the ClamAV CVD signature-verification certs directory."""
    candidates = [
        "/etc/clamav/certs",
        "/usr/share/clamav/certs",
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def clamav_env() -> dict[str, str]:
    """Return env dict for ClamAV on Linux."""
    env = {**os.environ}
    certs = find_certs_dir()
    if certs:
        env["CVD_CERTS_DIR"] = certs
    return env


def is_app_bundle() -> bool:
    """Return False — packaged install detection not yet implemented."""
    return False


def daemons_approved() -> bool:
    """Return True (dev mode — no daemon approval needed)."""
    return True


def has_full_disk_access() -> bool:
    """Return True (dev mode — no permission check needed)."""
    return True


def open_fda_settings():
    """No-op on Linux — no equivalent to macOS Full Disk Access."""
    logger.info(
        "Antivirus: Linux has no FDA equivalent. "
        "Grant CAP_SYS_ADMIN or run as root for real-time protection.",
    )


def open_login_items_settings():
    """No-op on Linux — no equivalent to macOS Login Items."""
    logger.info(
        "Antivirus: use 'systemctl enable clamav-daemon' to enable "
        "ClamAV on startup.",
    )


def ensure_daemons_registered():
    """No-op — systemd service registration not yet implemented."""
    logger.debug("Antivirus: daemon registration not yet implemented on Linux")


def activate_system_daemons() -> tuple[bool, str]:
    """Not yet implemented on Linux."""
    return False, "System daemon activation is not yet implemented on Linux."


def deactivate_system_daemons() -> tuple[bool, str]:
    """Not yet implemented on Linux."""
    return False, "System daemon deactivation is not yet implemented on Linux."


def is_clamonacc_running() -> bool:
    """Return False — real-time protection check not yet implemented."""
    return False
