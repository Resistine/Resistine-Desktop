"""ClamAV platform module — Windows (stub).

Every function raises NotImplementedError with implementation guidance.
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
import sys


# ── Platform interface ────────────────────────────────────


def system_db_dir() -> str | None:
    """Return system DB dir path if it exists, else None."""
    return None


def system_db_dir_writable() -> str | None:
    """Return system DB dir if writable by the current user, else None."""
    return None


def system_clamd_socket_path() -> str:
    """Return the clamd connection address.

    IMPORTANT: Windows ClamAV uses TCP, not Unix sockets.
    Return "127.0.0.1:3310" (the default ClamAV TCP address).
    The common module's _ping_socket/_contscan_socket will need
    a TCP code path — coordinate with clamav_common.py changes.
    """
    raise NotImplementedError(
        "Windows: ClamAV uses TCP:3310, not Unix sockets. "
        "Return '127.0.0.1:3310'. Also update clamav_common._ping_socket "
        "and _contscan_socket to handle TCP connections."
    )


def system_clamd_conf_path() -> str:
    """Return the system-level clamd.conf location.

    Common location: C:\\Program Files\\ClamAV\\clamd.conf
    or %ProgramData%\\ClamAV\\clamd.conf.
    """
    raise NotImplementedError(
        "Windows: return clamd.conf path. "
        "Check %ProgramFiles%\\ClamAV\\clamd.conf, "
        "%ProgramData%\\ClamAV\\clamd.conf."
    )


def find_binary(name: str) -> str | None:
    """Find a ClamAV binary on Windows.

    Search order:
      1. Bundled binaries (relative to frozen executable)
      2. Common install locations:
         C:\\Program Files\\ClamAV\\{name}.exe
         C:\\Program Files\\Resistine\\ClamAV\\{name}.exe
      3. System PATH via shutil.which (appends .exe automatically)
    """
    raise NotImplementedError(
        "Windows: find ClamAV binary. Check bundled paths, "
        "C:\\Program Files\\ClamAV\\{name}.exe, then shutil.which(name)."
    )


def find_certs_dir() -> str | None:
    """Locate the ClamAV CVD signature-verification certs directory.

    On Windows, check:
      - Bundled certs relative to the executable
      - C:\\Program Files\\ClamAV\\certs\\
      - C:\\Program Files\\Resistine\\ClamAV\\certs\\
    """
    raise NotImplementedError(
        "Windows: find CVD certs directory relative to install path."
    )


def clamav_env() -> dict[str, str]:
    """Return env dict for ClamAV on Windows.

    Set PATH to include ClamAV binary directory.
    Set CVD_CERTS_DIR if find_certs_dir() returns a path.
    Windows uses its own certificate store, so SSL_CERT_FILE
    is typically not needed.
    """
    raise NotImplementedError(
        "Windows: build ClamAV environment dict. "
        "Prepend ClamAV bin dir to PATH, set CVD_CERTS_DIR."
    )


def is_app_bundle() -> bool:
    """Return True if running from an installed package (e.g. MSI/MSIX).

    Check if the executable is under Program Files or a known
    install directory.
    """
    raise NotImplementedError(
        "Windows: detect if running from an installed package. "
        "Check sys.executable path for Program Files or install dir."
    )


def daemons_approved() -> bool:
    """Check if ClamAV Windows service is registered and approved.

    Use `sc.exe query ClamAV` or Windows service APIs.
    """
    raise NotImplementedError(
        "Windows: check ClamAV service status via sc.exe query or win32service."
    )


def has_full_disk_access() -> bool:
    """Check if real-time monitor has needed permissions.

    On Windows, clamonacc needs admin rights. Check if the current
    process is elevated (running as Administrator).
    Use ctypes.windll.shell32.IsUserAnAdmin().
    """
    raise NotImplementedError(
        "Windows: check if running as Administrator via "
        "ctypes.windll.shell32.IsUserAnAdmin()."
    )


def open_fda_settings():
    """Open Windows Security settings or UAC prompt.

    Could open Windows Security > Virus & threat protection settings,
    or show instructions for running as Administrator.
    """
    raise NotImplementedError(
        "Windows: open relevant security settings. "
        "Consider os.startfile or subprocess with 'start ms-settings:...'."
    )


def open_login_items_settings():
    """Open Windows service management UI.

    Could open services.msc or Task Scheduler.
    """
    raise NotImplementedError(
        "Windows: open services.msc or relevant service management UI."
    )


def ensure_daemons_registered():
    """Register ClamAV as a Windows service.

    Use sc.exe to create the service:
      sc.exe create ClamAV binpath= "C:\\...\\clamd.exe --service"
    Requires Administrator privileges (UAC elevation).
    """
    raise NotImplementedError(
        "Windows: register ClamAV as a Windows service via sc.exe create. "
        "Requires UAC elevation."
    )


def activate_system_daemons() -> tuple[bool, str]:
    """Start ClamAV Windows service.

    Use `sc.exe start ClamAV` with UAC elevation.
    Return (success, message).
    """
    raise NotImplementedError(
        "Windows: start ClamAV service via sc.exe start with UAC elevation."
    )


def deactivate_system_daemons() -> tuple[bool, str]:
    """Stop ClamAV Windows service.

    Use `sc.exe stop ClamAV` with UAC elevation.
    Return (success, message).
    """
    raise NotImplementedError(
        "Windows: stop ClamAV service via sc.exe stop with UAC elevation."
    )


def is_clamonacc_running() -> bool:
    """Check if real-time protection is active.

    On Windows, clamonacc may not exist. Real-time protection
    might use a different mechanism (e.g. a Windows service
    with file system filter driver). Check the ClamAV service status.
    """
    raise NotImplementedError(
        "Windows: check if ClamAV real-time protection service is running."
    )
