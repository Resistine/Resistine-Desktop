"""ClamAV platform module — Linux.

Binary discovery via PATH, systemd daemon management (clamav-daemon /
clamd@scan, clamav-freshclam, clamav-clamonacc) via pkexec/sudo, and
distro-aware package installation through utils.distro.LinuxDistro.

See clamav_platform_darwin.py for the macOS reference.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import shutil
import subprocess
import time

from utils.distro import LinuxDistro
from utils.logger import logger


# ── Probed system paths ──────────────────────────────────

_SYSTEM_DB_DIR_CANDIDATES = [
    "/var/lib/clamav",        # Debian, Ubuntu, Arch, openSUSE
    "/var/lib/clamd/scan",    # Fedora, RHEL, CentOS (clamd@scan)
]

_SYSTEM_SOCKET_CANDIDATES = [
    "/run/clamav/clamd.ctl",
    "/var/run/clamav/clamd.ctl",
    "/run/clamd.scan/clamd.sock",
    "/var/run/clamd.scan/clamd.sock",
    "/var/lib/clamav/clamd.sock",
]

_SYSTEM_CONF_CANDIDATES = [
    "/etc/clamav/clamd.conf",   # Debian/Ubuntu/Arch
    "/etc/clamd.d/scan.conf",   # Fedora/RHEL
]


# ── Privileged execution (pkexec → sudo) ─────────────────


def _run_privileged(command: list[str], timeout: int = 300) -> tuple[bool, str]:
    """Run *command* as root via pkexec, falling back to sudo+password dialog.

    Returns ``(success, combined_output)``.
    """
    if shutil.which("pkexec"):
        try:
            executable = shutil.which(command[0]) or command[0]
            full_cmd = ["pkexec", executable, *command[1:]]
            logger.info(f"ClamAV: pkexec — {full_cmd}")
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode == 0:
                return True, (result.stdout or "").strip()
            err = (result.stderr or result.stdout or "").strip()
            logger.warning(
                f"ClamAV: pkexec failed (code {result.returncode}): {err}. "
                "Falling back to sudo.",
            )
        except FileNotFoundError:
            logger.warning("ClamAV: pkexec not found, falling back to sudo")
        except subprocess.TimeoutExpired:
            return False, "pkexec timed out."
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(f"ClamAV: pkexec error: {exc}")

    try:
        from gui.dialogs import CTkPasswordDialog
    except ImportError:
        return False, "GUI password dialog unavailable."

    dialog = CTkPasswordDialog(
        title="Authentication Required",
        text="Enter password to configure antivirus protection:",
    )
    password = dialog.get_input()
    if not password:
        return False, "User cancelled password prompt."

    try:
        result = subprocess.run(
            ["sudo", "-S", "-p", "", *command],
            input=password + "\n",
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return True, (result.stdout or "").strip()
        return False, (result.stderr or result.stdout or "").strip() or (
            f"sudo exited with code {result.returncode}"
        )
    except subprocess.TimeoutExpired:
        return False, "Command timed out."
    except Exception as exc:
        return False, str(exc)


# ── Distro-specific service / package mapping ────────────


def _service_names() -> tuple[str, str, str]:
    """Return (clamd_service, freshclam_service, clamonacc_service)."""
    if LinuxDistro.is_fedora_like():
        return ("clamd@scan", "clamav-freshclam", "clamav-clamonacc")
    # Debian/Ubuntu, Arch, openSUSE, and most others use these names.
    return ("clamav-daemon", "clamav-freshclam", "clamav-clamonacc")


def _packages_to_install() -> tuple[list[str], list[str]]:
    """Return ``(required, optional)`` ClamAV package lists for this distro.

    Required packages must all be available or the install fails.
    Optional packages (clamonacc on distros that haven't packaged it,
    for example) are installed in a separate transaction so a missing
    one doesn't abort the whole setup.

    Fedora/RHEL/CentOS naming differs from Debian:
        clamav          → clamscan
        clamd           → clamd binary + /usr/lib/systemd/system/clamd@.service
        clamav-update   → freshclam
        clamav-clamonacc → clamonacc (Fedora 42+; missing on older releases)
    """
    if LinuxDistro.is_fedora_like():
        return ["clamav", "clamd", "clamav-update"], ["clamav-clamonacc"]
    if LinuxDistro.is_arch_like():
        return ["clamav"], []
    # Debian / Ubuntu / derivatives.
    return (
        ["clamav", "clamav-daemon", "clamav-freshclam"],
        ["clamav-clamonacc"],
    )


def _systemctl_is_active(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _systemctl_has_unit(service: str) -> bool:
    """Return True if systemd knows about *service*."""
    try:
        r = subprocess.run(
            ["systemctl", "cat", service],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# ── Platform interface ────────────────────────────────────


def system_db_dir() -> str | None:
    """Return system DB dir path if it exists, else None."""
    for path in _SYSTEM_DB_DIR_CANDIDATES:
        if os.path.isdir(path):
            return path
    return None


def system_db_dir_writable() -> str | None:
    """Return system DB dir if writable by the current user, else None.

    Normally the ``clamav`` system user owns the DB dir, so this returns
    None for non-root users — freshclam is run via systemd as that user.
    """
    d = system_db_dir()
    if d and os.access(d, os.W_OK):
        return d
    return None


def system_clamd_socket_path() -> str:
    """Return the system-level clamd socket path."""
    for path in _SYSTEM_SOCKET_CANDIDATES:
        if os.path.exists(path):
            return path
    return _SYSTEM_SOCKET_CANDIDATES[0]


def system_clamd_conf_path() -> str:
    """Return the system-level clamd.conf location."""
    for path in _SYSTEM_CONF_CANDIDATES:
        if os.path.exists(path):
            return path
    # Fall back to the distro-appropriate default even if not yet written.
    if LinuxDistro.is_fedora_like():
        return "/etc/clamd.d/scan.conf"
    return "/etc/clamav/clamd.conf"


def find_binary(name: str) -> str | None:
    """Find a ClamAV binary on Linux via PATH lookup."""
    return shutil.which(name)


def find_certs_dir() -> str | None:
    """Distro-packaged freshclam uses the system CA bundle — no override."""
    return None


def clamav_env() -> dict[str, str]:
    """Return env dict for ClamAV on Linux.

    Ensures SSL_CERT_FILE is set so user-level freshclam (used for dev
    scans before system daemons are installed) can verify TLS.
    """
    env = dict(os.environ)
    if "SSL_CERT_FILE" not in env:
        for ca in (
            "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu/Arch
            "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL/Fedora
            "/etc/ssl/cert.pem",                     # fallback
        ):
            if os.path.isfile(ca):
                env["SSL_CERT_FILE"] = ca
                break
    return env


def is_app_bundle() -> bool:
    """Map the macOS app-bundle concept to 'system-wide daemon install'.

    Returns True when systemd is available — activate_system_daemons()
    will install the distro package if clamd isn't present yet. This
    makes the Start Protection UI path work the same as on macOS.
    """
    return LinuxDistro.is_systemd()


def daemons_approved() -> bool:
    """Linux has no Login Items equivalent — approval is implicit."""
    return True


def has_full_disk_access() -> bool:
    """Linux has no FDA equivalent — the clamav system user has access."""
    return True


def open_fda_settings():
    """No-op on Linux — no Full Disk Access equivalent."""
    logger.info(
        "Antivirus: Linux has no Full Disk Access equivalent. "
        "The 'clamav' system user reads files on behalf of the daemon.",
    )


def open_login_items_settings():
    """No-op on Linux — services are managed by systemd."""
    clamd_svc, _fresh, _onacc = _service_names()
    logger.info(
        f"Antivirus: manage the service via 'systemctl enable {clamd_svc}'.",
    )


def ensure_daemons_registered():
    """No-op on Linux — systemd units are registered by the distro package."""
    logger.debug(
        "Antivirus: systemd handles daemon registration on Linux "
        "(done by the distro package).",
    )


def is_clamonacc_running() -> bool:
    """Check if clamonacc is running (by process name)."""
    try:
        r = subprocess.run(
            ["pgrep", "-x", "clamonacc"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# ── System daemon activation ─────────────────────────────


def _install_packages_if_missing() -> tuple[bool, str]:
    """Install ClamAV packages via the distro package manager.

    No-op if ``clamd`` is already on PATH. Returns (success, message).

    Runs the required and optional installs together under one admin
    prompt: required first, then optional in a ``|| true`` trailer so a
    missing clamonacc package on older distros doesn't abort setup.
    """
    if shutil.which("clamd"):
        return True, "ClamAV already installed."

    required, optional = _packages_to_install()

    required_cmd = LinuxDistro.get_install_command(required)
    if not required_cmd:
        return False, (
            "No supported package manager found. Install ClamAV "
            f"manually ({', '.join(required)}) and try again."
        )

    parts: list[str] = []
    # Refresh the package index on Debian-likes so the install doesn't
    # fail on a stale apt cache.
    if LinuxDistro.is_debian_like():
        parts.append("apt-get update")
    parts.append(" ".join(_shell_quote(c) for c in required_cmd))

    if optional:
        optional_cmd = LinuxDistro.get_install_command(optional)
        if optional_cmd:
            parts.append(
                "(" + " ".join(_shell_quote(c) for c in optional_cmd)
                + " || true)",
            )

    script = " && ".join(parts)
    ok, out = _run_privileged(["sh", "-c", script])

    if not ok:
        return False, out or "Package installation failed."

    if not shutil.which("clamd"):
        return False, (
            "Package install completed but clamd is still missing. "
            "Check your package manager logs."
        )
    return True, "ClamAV packages installed."


def _shell_quote(s: str) -> str:
    """Quote *s* for POSIX shell."""
    import shlex
    return shlex.quote(s)


def _prepare_config_script() -> str:
    """Shell snippet that comments out 'Example' lines in distro-stock configs.

    Fedora and older Debian ship clamd.conf/freshclam.conf with a lone
    ``Example`` line that prevents the daemon from starting until it's
    removed. This is safe to run on every invocation.
    """
    targets = [
        "/etc/clamav/clamd.conf",
        "/etc/clamav/freshclam.conf",
        "/etc/clamd.d/scan.conf",
        "/etc/freshclam.conf",
    ]
    cmds = []
    for t in targets:
        q = _shell_quote(t)
        cmds.append(
            f"if [ -f {q} ]; then sed -i 's/^Example$/#Example/' {q}; fi",
        )
    return "; ".join(cmds)


def activate_system_daemons() -> tuple[bool, str]:
    """Install (if missing) and start system-level ClamAV daemons.

    Flow:
      1. Install distro packages if clamd isn't already on PATH.
      2. Comment out any 'Example' stanzas left in stock configs.
      3. Enable + start freshclam (populates DB) and clamd.
      4. Enable + start clamav-clamonacc if the unit exists.
      5. Wait for clamd to become responsive via the Unix socket.
    """
    if not LinuxDistro.is_systemd():
        return False, (
            "systemd is not available. Start clamd manually for your "
            "init system (OpenRC, runit, etc.)."
        )

    installed_ok, install_msg = _install_packages_if_missing()
    if not installed_ok:
        return False, install_msg

    clamd_svc, fresh_svc, onacc_svc = _service_names()

    prep = _prepare_config_script()
    # Freshclam first so the DB exists before clamd loads. clamonacc is
    # best-effort (not all distros package it yet).
    script = (
        f"{prep}; "
        f"systemctl daemon-reload; "
        f"systemctl enable --now {fresh_svc} || true; "
        f"systemctl enable --now {clamd_svc}; "
        f"systemctl enable --now {onacc_svc} || true"
    )
    ok, out = _run_privileged(["sh", "-c", script], timeout=600)
    if not ok:
        return False, out or "Failed to enable ClamAV services."

    # Wait for clamd to respond on its socket (signature load takes a while).
    sock = system_clamd_socket_path()
    from plugins.antivirus.clamav_common import _ping_socket

    for _ in range(120):  # up to 60 seconds
        time.sleep(0.5)
        if _ping_socket(sock):
            logger.info("ClamAV: system clamd is running")
            # Give clamonacc a few seconds to stabilise once clamd answers.
            for _w in range(20):
                if is_clamonacc_running():
                    logger.info("ClamAV: clamonacc is running")
                    break
                time.sleep(0.5)
            else:
                logger.warning(
                    "ClamAV: clamonacc not running after activation — "
                    "real-time protection may not be available on this distro.",
                )
            return True, "Protection activated."

    if _systemctl_is_active(clamd_svc):
        logger.info("ClamAV: clamd active but still loading signatures")
        return True, "Protection starting — signatures loading in background."

    return False, (
        f"clamd did not start. Check 'journalctl -u {clamd_svc}' for details."
    )


def deactivate_system_daemons() -> tuple[bool, str]:
    """Stop and disable system-level ClamAV daemons.

    Leaves the distro packages installed so re-activation is fast.
    """
    if not LinuxDistro.is_systemd():
        return False, "systemd is not available."

    clamd_svc, fresh_svc, onacc_svc = _service_names()
    script = (
        f"systemctl disable --now {onacc_svc} 2>/dev/null || true; "
        f"systemctl disable --now {clamd_svc} 2>/dev/null || true; "
        f"systemctl disable --now {fresh_svc} 2>/dev/null || true"
    )
    ok, out = _run_privileged(["sh", "-c", script], timeout=60)
    if ok:
        return True, "Protection deactivated."
    return False, out or "Failed to stop ClamAV services."
