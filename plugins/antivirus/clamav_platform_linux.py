"""ClamAV platform module — Linux (stub).

Every function raises NotImplementedError with implementation guidance.
See clamav_platform_darwin.py for a working reference implementation.

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
    """Return the system-level clamd socket path.

    Linux distros place clamd's socket in different locations:
      - Debian/Ubuntu: /var/run/clamav/clamd.ctl
      - RHEL/Fedora:   /var/run/clamd.scan/clamd.sock
      - Arch:          /var/lib/clamav/clamd.sock
    Probe multiple candidates and return the first that exists,
    or a sensible default.
    """
    raise NotImplementedError(
        "Linux: return the system clamd socket path. "
        "Probe /var/run/clamav/clamd.ctl, /var/run/clamd.scan/clamd.sock, "
        "/var/lib/clamav/clamd.sock."
    )


def system_clamd_conf_path() -> str:
    """Return the system-level clamd.conf location.

    Common locations:
      - /etc/clamav/clamd.conf (Debian/Ubuntu)
      - /etc/clamd.d/scan.conf (RHEL/Fedora)
    """
    raise NotImplementedError(
        "Linux: return system clamd.conf path. "
        "Probe /etc/clamav/clamd.conf, /etc/clamd.d/scan.conf."
    )


def find_binary(name: str) -> str | None:
    """Find a ClamAV binary on Linux.

    Search order:
      1. Bundled binaries (if running from an AppImage/package)
      2. System PATH via shutil.which
      3. Common package manager install locations:
         /usr/bin/, /usr/sbin/, /usr/local/bin/
    """
    raise NotImplementedError(
        "Linux: find ClamAV binary by name. "
        "Check bundled paths first, then shutil.which(name), "
        "then /usr/bin/{name}, /usr/sbin/{name}, /usr/local/bin/{name}."
    )


def find_certs_dir() -> str | None:
    """Locate the ClamAV CVD signature-verification certs directory.

    On Linux, ClamAV packages typically install certs to:
      - /etc/clamav/certs/
      - /usr/share/clamav/certs/
    Also check bundled certs if running from a packaged install.
    """
    raise NotImplementedError(
        "Linux: find CVD certs directory. "
        "Check /etc/clamav/certs/, /usr/share/clamav/certs/, "
        "and bundled certs relative to the install path."
    )


def clamav_env() -> dict[str, str]:
    """Return env dict with library paths for ClamAV on Linux.

    Set LD_LIBRARY_PATH for bundled libraries (if any).
    Set SSL_CERT_FILE if not already set (common CA paths):
      - /etc/ssl/certs/ca-certificates.crt (Debian/Ubuntu)
      - /etc/pki/tls/certs/ca-bundle.crt (RHEL/Fedora)
    Set CVD_CERTS_DIR if find_certs_dir() returns a path.
    """
    raise NotImplementedError(
        "Linux: build ClamAV environment dict. "
        "Set LD_LIBRARY_PATH for bundled libs, SSL_CERT_FILE, CVD_CERTS_DIR."
    )


def is_app_bundle() -> bool:
    """Return True if running from a packaged install (e.g. AppImage, .deb).

    On Linux this might check for an AppImage mount point
    or whether the executable lives under /opt/resistine/.
    """
    raise NotImplementedError(
        "Linux: detect if running from a packaged install. "
        "Check for AppImage env vars or /opt/resistine/ path."
    )


def daemons_approved() -> bool:
    """Check if ClamAV daemons are registered with systemd.

    On Linux, use `systemctl is-enabled clamav-daemon` or similar.
    If not running from a package install, return True (dev mode).
    """
    raise NotImplementedError(
        "Linux: check systemd service status. "
        "Run: systemctl is-enabled clamav-daemon / clamav-freshclam."
    )


def has_full_disk_access() -> bool:
    """Check if real-time monitor has needed permissions.

    On Linux, clamonacc needs root for fanotify. Check if the
    current process has CAP_SYS_ADMIN or is running as root.
    """
    raise NotImplementedError(
        "Linux: check if process has CAP_SYS_ADMIN or is root (os.geteuid() == 0)."
    )


def open_fda_settings():
    """Open OS permissions UI.

    On Linux there is no GUI equivalent of macOS FDA. This could:
      - Log a message explaining that root/CAP_SYS_ADMIN is needed
      - Open a polkit dialog
      - Be a no-op with a logger.info message
    """
    raise NotImplementedError(
        "Linux: no direct equivalent to macOS FDA settings. "
        "Consider logging instructions for granting CAP_SYS_ADMIN."
    )


def open_login_items_settings():
    """Open daemon approval UI.

    On Linux this could open systemd service management,
    or simply be a no-op with documentation.
    """
    raise NotImplementedError(
        "Linux: no direct equivalent. Consider opening systemctl status "
        "or logging instructions for enabling the systemd service."
    )


def ensure_daemons_registered():
    """Register ClamAV daemons with the system service manager.

    On Linux with systemd:
      1. Write unit files to /etc/systemd/system/ (needs root)
      2. Run systemctl daemon-reload
      3. Run systemctl enable clamav-daemon clamav-freshclam
    Use pkexec or sudo for privilege elevation.
    """
    raise NotImplementedError(
        "Linux: register systemd services for clamd and freshclam. "
        "Write unit files, run systemctl daemon-reload && systemctl enable."
    )


def activate_system_daemons() -> tuple[bool, str]:
    """Start ClamAV daemons with privilege elevation.

    On Linux: `pkexec systemctl start clamav-daemon` or
    `sudo systemctl start clamav-daemon`.
    Return (success, message).
    """
    raise NotImplementedError(
        "Linux: start clamd/freshclam via systemctl with pkexec/sudo."
    )


def deactivate_system_daemons() -> tuple[bool, str]:
    """Stop ClamAV daemons with privilege elevation.

    On Linux: `pkexec systemctl stop clamav-daemon`.
    Return (success, message).
    """
    raise NotImplementedError(
        "Linux: stop clamd/freshclam via systemctl with pkexec/sudo."
    )


def is_clamonacc_running() -> bool:
    """Check if clamonacc (real-time protection) is active.

    Use `pgrep -x clamonacc` or check systemd service status.
    """
    raise NotImplementedError(
        "Linux: check if clamonacc process is running via pgrep or systemctl."
    )
