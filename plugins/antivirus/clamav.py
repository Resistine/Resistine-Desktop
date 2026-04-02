"""ClamAV backend — binary discovery, config, daemon, scanning, quarantine.

Locates bundled ClamAV binaries (clamscan, clamdscan, clamd, freshclam,
clamonacc) and manages all backend operations for the Antivirus plugin.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import glob
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from utils.logger import logger
from utils.settings import get_config_dir

# ── Paths ────────────────────────────────────────────────

_CLAMAV_DATA_DIR = os.path.join(get_config_dir(), "clamav")
_DB_DIR = os.path.join(_CLAMAV_DATA_DIR, "db")
_LOG_DIR = os.path.join(_CLAMAV_DATA_DIR, "log")
_RUN_DIR = os.path.join(_CLAMAV_DATA_DIR, "run")
_QUARANTINE_DIR = os.path.join(_CLAMAV_DATA_DIR, "quarantine")
_CLAMD_CONF = os.path.join(_CLAMAV_DATA_DIR, "clamd.conf")
_FRESHCLAM_CONF = os.path.join(_CLAMAV_DATA_DIR, "freshclam.conf")
_CLAMD_SOCKET = os.path.join(_RUN_DIR, "clamd.sock")
_SYSTEM_CLAMD_SOCKET = "/Library/Application Support/Resistine/clamav/run/clamd.sock"
_SYSTEM_CLAMD_CONF = "/Library/Application Support/Resistine/clamav/clamd.conf"
_CLAMD_PID = os.path.join(_RUN_DIR, "clamd.pid")
_WHITELIST_FILE = os.path.join(_CLAMAV_DATA_DIR, "whitelist.txt")

# SMAppService daemon plists (in Contents/Library/LaunchDaemons/).
# Order matters: clamd must be registered before clamonacc.
_DAEMON_PLISTS = [
    "com.resistine.desktop.clamd.plist",
    "com.resistine.desktop.clamonacc.plist",
]

# Legacy plist paths from pre-SMAppService installs
_LEGACY_PLIST_PATHS = [
    "/Library/LaunchDaemons/com.resistine.clamd.plist",
    "/Library/LaunchDaemons/com.resistine.clamonacc.plist",
    "/Library/LaunchDaemons/com.resistine.desktop.clamd.plist",
    "/Library/LaunchDaemons/com.resistine.desktop.clamonacc.plist",
]


def _find_certs_dir() -> str | None:
    """Locate the ClamAV CVD signature-verification certs directory."""
    candidates = []

    # 1. Bundled app (frozen build)
    if getattr(sys, "frozen", False):
        candidates.append(
            os.path.join(os.path.dirname(sys.executable), "..", "certs"),
        )

    # 2. Dev build artifacts
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    candidates.append(
        os.path.join(project_root, "scripts", "build", "clamav-artifacts", "certs"),
    )

    for path in candidates:
        resolved = os.path.realpath(path)
        if os.path.isdir(resolved) and os.path.isfile(
            os.path.join(resolved, "clamav.crt"),
        ):
            return resolved
    return None


def _ensure_dirs():
    for d in (_DB_DIR, _LOG_DIR, _RUN_DIR, _QUARANTINE_DIR):
        os.makedirs(d, exist_ok=True)


# ── Binary discovery ─────────────────────────────────────


def _find_binary(name: str) -> str | None:
    """Find a ClamAV binary: bundled Helpers → installed app → dev artifacts → PATH."""
    candidates = []

    # 1. Bundled app (frozen build)
    if getattr(sys, "frozen", False):
        helpers = os.path.join(
            os.path.dirname(sys.executable), "..", "Helpers",
        )
        candidates.append(os.path.join(helpers, name))

    # 2. Installed app bundle (for dev mode using signed binaries)
    candidates.append(f"/Applications/Resistine.app/Contents/Helpers/{name}")

    # 3. Dev build artifacts
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    artifacts = os.path.join(
        project_root, "scripts", "build", "clamav-artifacts", "binaries",
    )
    candidates.append(os.path.join(artifacts, name))

    for path in candidates:
        resolved = os.path.realpath(path)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved

    # 4. System PATH
    return shutil.which(name)


def _clamav_env() -> dict[str, str]:
    """Return env dict with library paths, SSL certs, and CVD certs for ClamAV."""
    env = os.environ.copy()

    # Override the CVD signature-verification certs directory. The CI-built
    # binaries have a hardcoded path from the build machine that doesn't exist
    # on end-user systems.
    if "CVD_CERTS_DIR" not in env:
        certs_dir = _find_certs_dir()
        if certs_dir:
            env["CVD_CERTS_DIR"] = certs_dir

    # Point OpenSSL at the system CA bundle so freshclam can verify TLS.
    # The CI-built binary has a hardcoded (non-existent) certs path.
    if "SSL_CERT_FILE" not in env:
        for ca_path in (
            "/etc/ssl/cert.pem",                           # macOS
            "/etc/ssl/certs/ca-certificates.crt",          # Debian/Ubuntu
            "/etc/pki/tls/certs/ca-bundle.crt",            # RHEL/Fedora
        ):
            if os.path.isfile(ca_path):
                env["SSL_CERT_FILE"] = ca_path
                break

    if not getattr(sys, "frozen", False):
        lib_dirs = []
        # Installed app bundle frameworks
        app_fw = "/Applications/Resistine.app/Contents/Frameworks"
        if os.path.isdir(app_fw):
            lib_dirs.append(app_fw)
        # Dev build artifacts
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(__file__)),
        )
        lib_dir = os.path.join(
            project_root, "scripts", "build", "clamav-artifacts", "lib",
        )
        if os.path.isdir(lib_dir):
            lib_dirs.append(lib_dir)
        if lib_dirs:
            existing = env.get("DYLD_LIBRARY_PATH", "")
            combined = ":".join(lib_dirs)
            env["DYLD_LIBRARY_PATH"] = (
                f"{combined}:{existing}" if existing else combined
            )
    return env


def get_binaries() -> dict[str, str | None]:
    """Return dict of binary name → path (or None)."""
    names = ("clamscan", "clamdscan", "clamd", "freshclam", "clamonacc")
    return {n: _find_binary(n) for n in names}


def is_available() -> bool:
    """True if at least clamscan is found."""
    return _find_binary("clamscan") is not None


# ── Config generation ────────────────────────────────────


def _write_clamd_conf():
    _ensure_dirs()
    conf = f"""\
# Auto-generated by Resistine — do not edit manually
LocalSocket {_CLAMD_SOCKET}
PidFile {_CLAMD_PID}
DatabaseDirectory {_DB_DIR}
LogFile {os.path.join(_LOG_DIR, "clamd.log")}
LogFileMaxSize 5M
LogTime yes
TemporaryDirectory /tmp
MaxDirectoryRecursion 20
FollowDirectorySymlinks yes
ExcludePath ^/proc
ExcludePath ^/sys
ExcludePath ^/dev
"""
    with open(_CLAMD_CONF, "w") as f:
        f.write(conf)


def _write_freshclam_conf():
    _ensure_dirs()
    conf = f"""\
# Auto-generated by Resistine — do not edit manually
DatabaseDirectory {_DB_DIR}
UpdateLogFile {os.path.join(_LOG_DIR, "freshclam.log")}
LogFileMaxSize 2M
LogTime yes
DatabaseMirror database.clamav.net
NotifyClamd {_CLAMD_CONF}
"""
    # Override the hardcoded CVD certs path baked into the CI-built binary.
    certs_dir = _find_certs_dir()
    if certs_dir:
        conf += f"CVDCertsDirectory {certs_dir}\n"

    with open(_FRESHCLAM_CONF, "w") as f:
        f.write(conf)


def ensure_config():
    """Create/refresh config files and directories.

    Always regenerates configs because they are auto-generated from current
    runtime paths (e.g. CVDCertsDirectory depends on where binaries are found).
    """
    _ensure_dirs()
    _write_clamd_conf()
    _write_freshclam_conf()


# ── Signature database info ──────────────────────────────


def get_db_info() -> dict[str, str]:
    """Return signature count and last-updated date from local DB files."""
    info: dict[str, str] = {"signatures": "\u2014", "last_updated": "\u2014"}

    cvd_files = glob.glob(os.path.join(_DB_DIR, "*.cvd"))
    cvd_files += glob.glob(os.path.join(_DB_DIR, "*.cld"))

    if not cvd_files:
        return info

    total_sigs = 0
    latest_mtime = 0.0

    for cvd in cvd_files:
        try:
            with open(cvd, "rb") as f:
                header = f.read(512).decode("ascii", errors="replace")
            # CVD header format: ClamAV-VDB:date:ver:sigs:...
            parts = header.split(":")
            if len(parts) >= 4:
                total_sigs += int(parts[3])
        except (OSError, ValueError):
            pass
        mtime = os.path.getmtime(cvd)
        if mtime > latest_mtime:
            latest_mtime = mtime

    if total_sigs > 0:
        info["signatures"] = f"{total_sigs:,}"
    if latest_mtime > 0:
        info["last_updated"] = time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(latest_mtime),
        )

    return info


def has_database() -> bool:
    """True if at least one signature database file exists."""
    return bool(
        glob.glob(os.path.join(_DB_DIR, "*.cvd"))
        or glob.glob(os.path.join(_DB_DIR, "*.cld"))
    )


# ── Freshclam (signature updates) ────────────────────────


def run_freshclam(
    on_line=None,
) -> tuple[bool, str]:
    """Run freshclam to update signature databases.

    Returns (success, summary_message).
    """
    binary = _find_binary("freshclam")
    if not binary:
        return False, "freshclam binary not found."

    ensure_config()
    cmd = [binary, "--config-file", _FRESHCLAM_CONF, "--stdout"]
    logger.info(f"ClamAV: running freshclam — {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=_clamav_env(),
        )
        lines = []
        for line in proc.stdout:
            lines.append(line.rstrip())
            if on_line:
                on_line(line.rstrip())
        proc.wait()
        output = "\n".join(lines)

        if proc.returncode == 0:
            return True, "Signatures updated successfully."
        if "up to date" in output.lower():
            return True, "Signatures already up to date."
        return False, f"freshclam exited with code {proc.returncode}"
    except Exception as exc:
        return False, str(exc)


# ── Clamd daemon ──────────────────────────────────────────


def _clamd_pid_alive() -> bool:
    if not os.path.exists(_CLAMD_PID):
        return False
    try:
        with open(_CLAMD_PID) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _ping_socket(sock_path: str) -> bool:
    """Send zPING to a clamd Unix socket and return True on PONG."""
    if not os.path.exists(sock_path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock_path)
            s.sendall(b"zPING\0")
            return b"PONG" in s.recv(32)
    except (OSError, ConnectionRefusedError):
        return False


def _active_clamd_socket() -> str | None:
    """Return the socket path of a running clamd, or None.

    Checks the per-user socket first, then the system LaunchDaemon socket.
    """
    if _ping_socket(_CLAMD_SOCKET):
        return _CLAMD_SOCKET
    if _ping_socket(_SYSTEM_CLAMD_SOCKET):
        return _SYSTEM_CLAMD_SOCKET
    return None


def is_clamd_running() -> bool:
    """Check if clamd is responsive via its socket."""
    return _active_clamd_socket() is not None


def start_clamd() -> tuple[bool, str]:
    """Start clamd daemon if not already running."""
    if is_clamd_running():
        return True, "clamd already running."

    binary = _find_binary("clamd")
    if not binary:
        return False, "clamd binary not found."

    if not has_database():
        return False, "No signature database — run Update first."

    ensure_config()

    # Clean stale socket/pid
    for stale in (_CLAMD_SOCKET, _CLAMD_PID):
        if os.path.exists(stale):
            os.unlink(stale)

    cmd = [binary, "--config-file", _CLAMD_CONF]
    logger.info(f"ClamAV: starting clamd — {' '.join(cmd)}")

    try:
        subprocess.Popen(cmd, env=_clamav_env())
    except Exception as exc:
        return False, str(exc)

    # Wait for socket (up to 10s)
    for _ in range(20):
        time.sleep(0.5)
        if is_clamd_running():
            return True, "clamd started."
    return False, "clamd did not start in time."


def stop_clamd() -> tuple[bool, str]:
    """Stop clamd daemon."""
    if not _clamd_pid_alive():
        # Clean up stale files
        for f in (_CLAMD_SOCKET, _CLAMD_PID):
            if os.path.exists(f):
                os.unlink(f)
        return True, "clamd not running."

    try:
        with open(_CLAMD_PID) as f:
            pid = int(f.read().strip())
        os.kill(pid, 15)  # SIGTERM
        for _ in range(10):
            time.sleep(0.5)
            if not _clamd_pid_alive():
                break
        return True, "clamd stopped."
    except Exception as exc:
        return False, str(exc)


# ── SMAppService daemon registration (macOS 13+) ────────


def ensure_daemons_registered():
    """Register ClamAV LaunchDaemons via SMAppService.

    Called from the plugin init on a background thread. Follows the same
    pattern as the VPN helper registration in vpn_functions_darwin.py.
    """
    if not (
        ".app/Contents/MacOS" in sys.executable
        or ".app/Contents/MacOS" in os.path.abspath(sys.argv[0])
    ):
        logger.debug("Skipping ClamAV daemon registration (not an app bundle)")
        return

    try:
        from ServiceManagement import SMAppService
    except ImportError:
        logger.warning("ServiceManagement framework not available")
        return

    _cleanup_legacy_plists()

    needs_approval = False

    for plist_name in _DAEMON_PLISTS:
        try:
            service = SMAppService.daemonServiceWithPlistName_(plist_name)
        except Exception:
            try:
                service = SMAppService.daemonWithPlistName_(plist_name)
            except Exception:
                logger.warning(f"Could not create SMAppService for {plist_name}")
                continue

        status = int(service.status())
        status_map = {
            0: "notRegistered",
            1: "enabled",
            2: "requiresApproval",
            3: "notFound",
        }
        logger.info(
            f"ClamAV daemon {plist_name}: {status_map.get(status, 'unknown')}",
        )

        if status == 1:
            continue

        if status == 2:
            needs_approval = True
            continue

        # Not registered (0) or not found (3) — register
        success, err = service.registerAndReturnError_(None)
        if not success:
            logger.error(f"ClamAV daemon registration error ({plist_name}): {err}")
            if int(service.status()) == 2:
                needs_approval = True
        else:
            logger.info(f"ClamAV daemon {plist_name} registered successfully")

    if needs_approval:
        _prompt_daemon_approval()


def _cleanup_legacy_plists():
    """Remove old /Library/LaunchDaemons/ plists from pre-SMAppService installs."""
    found = [p for p in _LEGACY_PLIST_PATHS if os.path.exists(p)]
    if not found:
        return

    cmds = []
    for plist in found:
        cmds.append(f"launchctl bootout system '{plist}' 2>/dev/null")
        cmds.append(f"rm -f '{plist}'")

    script = "; ".join(cmds)
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    try:
        subprocess.run(
            [
                "osascript", "-e",
                f'do shell script "{escaped}" with administrator privileges',
            ],
            capture_output=True, text=True, timeout=30,
        )
        logger.info("Cleaned up legacy ClamAV LaunchDaemon plists")
    except Exception as e:
        logger.warning(f"Could not clean up legacy plists: {e}")


def _prompt_daemon_approval():
    """Prompt user to approve ClamAV daemons in System Settings > Login Items.

    Must schedule the dialog on the main thread — Tkinter is not thread-safe.
    """
    try:
        import tkinter as tk

        root = getattr(tk, "_default_root", None)
        if root is None:
            logger.warning("No Tk root available for daemon approval prompt")
            return

        def _show_dialog():
            from gui.dialogs import ask_yes_no

            def on_confirm(confirmed):
                if confirmed:
                    try:
                        from ServiceManagement import SMAppService

                        svc = SMAppService.daemonServiceWithPlistName_(
                            _DAEMON_PLISTS[0],
                        )
                        svc.openSystemSettingsLoginItems()
                        logger.info("Opened System Settings — Login Items")
                    except Exception:
                        pass

            ask_yes_no(
                root,
                "ClamAV Approval Required",
                "Resistine needs your approval to install ClamAV daemons "
                "for real-time malware protection.\n\n"
                "Click 'Yes' to open System Settings where you can enable "
                "them in Login Items.",
                on_confirm,
            )

        root.after(0, _show_dialog)
    except Exception as e:
        logger.error(f"Could not prompt for daemon approval: {e}")


# ── Scanning ──────────────────────────────────────────────


def scan_path(
    target: str,
    on_line: Callable | None = None,
    cancel: "threading.Event | None" = None,
) -> dict:
    """Scan a file or directory. Uses clamdscan if clamd is running,
    otherwise falls back to clamscan.

    Returns dict with keys: scanned, infected, infections, duration, error.
    Pass a threading.Event as *cancel* to allow early termination.
    """
    result = {
        "target": target,
        "scanned": 0,
        "infected": 0,
        "infections": [],
        "duration": "",
        "error": "",
    }

    # Prefer clamdscan (faster, uses running daemon)
    active_socket = _active_clamd_socket()
    if active_socket:
        binary = _find_binary("clamdscan")
    else:
        binary = _find_binary("clamscan")

    if not binary:
        result["error"] = "ClamAV not installed."
        return result

    if not active_socket and not has_database():
        result["error"] = "No signature database — run Update first."
        return result

    cmd = [binary, "--stdout"]
    if active_socket:
        # Use the config that matches the running daemon's socket
        if active_socket == _SYSTEM_CLAMD_SOCKET:
            cmd += ["--config-file", _SYSTEM_CLAMD_CONF]
        else:
            cmd += ["--config-file", _CLAMD_CONF]
    else:
        cmd += ["-d", _DB_DIR, "--recursive"]

        # --exclude-dir and --exclude are clamscan-only flags
        for skip in (".git", ".hg", ".svn", "node_modules", "__pycache__"):
            cmd += ["--exclude-dir", skip]
        for excluded in get_whitelist():
            if os.path.isdir(excluded):
                cmd += ["--exclude-dir", excluded]
            else:
                cmd += ["--exclude", excluded]

    cmd.append(target)

    logger.info(f"ClamAV: scanning — {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=_clamav_env(),
        )
        for line in proc.stdout:
            if cancel and cancel.is_set():
                proc.terminate()
                proc.wait(timeout=5)
                return result
            stripped = line.rstrip()
            if on_line:
                on_line(stripped)
            if "FOUND" in stripped:
                result["infections"].append(stripped)
            elif stripped.startswith("Scanned files:"):
                try:
                    result["scanned"] = int(stripped.split(":")[-1].strip())
                except ValueError:
                    pass
            elif stripped.startswith("Infected files:"):
                try:
                    result["infected"] = int(stripped.split(":")[-1].strip())
                except ValueError:
                    pass
            elif stripped.startswith("Time:"):
                result["duration"] = stripped.split(":", 1)[-1].strip()
        proc.wait()
    except Exception as exc:
        result["error"] = str(exc)

    return result


# ── Quarantine ────────────────────────────────────────────


def quarantine_file(filepath: str) -> tuple[bool, str]:
    """Move an infected file to the quarantine directory."""
    if not os.path.exists(filepath):
        return False, "File not found."
    _ensure_dirs()
    basename = os.path.basename(filepath)
    dest = os.path.join(_QUARANTINE_DIR, f"{basename}.quarantined")
    counter = 1
    while os.path.exists(dest):
        dest = os.path.join(
            _QUARANTINE_DIR, f"{basename}.{counter}.quarantined",
        )
        counter += 1
    try:
        shutil.move(filepath, dest)
        os.chmod(dest, 0o000)
        logger.info(f"ClamAV: quarantined {filepath} → {dest}")
        return True, dest
    except Exception as exc:
        return False, str(exc)


def list_quarantined() -> list[str]:
    """Return list of quarantined file paths."""
    _ensure_dirs()
    return sorted(glob.glob(os.path.join(_QUARANTINE_DIR, "*.quarantined")))


def restore_quarantined(quarantine_path: str, dest: str) -> tuple[bool, str]:
    """Restore a quarantined file to the given destination."""
    if not os.path.exists(quarantine_path):
        return False, "Quarantined file not found."
    try:
        os.chmod(quarantine_path, 0o644)
        shutil.move(quarantine_path, dest)
        return True, f"Restored to {dest}"
    except Exception as exc:
        return False, str(exc)


def delete_quarantined(quarantine_path: str) -> tuple[bool, str]:
    """Permanently delete a quarantined file."""
    if not os.path.exists(quarantine_path):
        return False, "File not found."
    try:
        os.chmod(quarantine_path, 0o644)
        os.unlink(quarantine_path)
        return True, "Deleted."
    except Exception as exc:
        return False, str(exc)


# ── Whitelist ─────────────────────────────────────────────


def get_whitelist() -> list[str]:
    """Return list of whitelisted paths."""
    _ensure_dirs()
    if not os.path.exists(_WHITELIST_FILE):
        return []
    with open(_WHITELIST_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def add_to_whitelist(path: str):
    """Add a path to the scan exclusion whitelist."""
    _ensure_dirs()
    current = get_whitelist()
    if path not in current:
        with open(_WHITELIST_FILE, "a") as f:
            f.write(path + "\n")
        logger.info(f"ClamAV: whitelisted {path}")


def remove_from_whitelist(path: str):
    """Remove a path from the whitelist."""
    current = get_whitelist()
    with open(_WHITELIST_FILE, "w") as f:
        for entry in current:
            if entry != path:
                f.write(entry + "\n")
    logger.info(f"ClamAV: removed from whitelist {path}")
