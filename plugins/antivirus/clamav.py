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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
LogVerbose yes
LogClean yes
MaxThreads 8
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


# ── Direct socket scanning ────────────────────────────────

_SKIP_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__"})
_PARALLEL_WORKERS = 6


def _contscan_socket(sock_path: str, file_path: str) -> str:
    """Send zCONTSCAN for one file to clamd; return the response line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(120)
        s.connect(sock_path)
        s.sendall(f"zCONTSCAN {file_path}\0".encode())
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\0" in buf:
                break
        return buf.decode(errors="replace").strip("\0").strip()


def _walk_files(target: str, whitelist: set[str]):
    """Yield scannable file paths under *target*.

    Both *target* and *whitelist* entries are resolved via realpath so
    symlinks and non-canonical paths are matched consistently.
    """
    resolved_wl = {os.path.realpath(p) for p in whitelist}
    resolved_target = os.path.realpath(target)

    # Block the entire walk when the target itself is whitelisted.
    if resolved_target in resolved_wl or any(
        resolved_target.startswith(w + os.sep) for w in resolved_wl
    ):
        return

    for root, dirs, files in os.walk(target):
        dirs[:] = [
            d for d in dirs
            if d not in _SKIP_DIRS
            and os.path.realpath(os.path.join(root, d)) not in resolved_wl
        ]
        for fname in files:
            fpath = os.path.join(root, fname)
            if (
                os.path.realpath(fpath) not in resolved_wl
                and not os.path.islink(fpath)
            ):
                yield fpath


def _format_duration(elapsed: float) -> str:
    mins, secs = divmod(int(elapsed), 60)
    if mins:
        return f"{elapsed:.3f} sec ({mins} m {secs} s)"
    return f"{elapsed:.3f} sec ({secs} s)"


def _scan_file_socket(
    target: str, sock_path: str, result: dict,
    on_line: Callable | None,
    cancel: "threading.Event | None" = None,
) -> dict:
    """Scan a single file via direct clamd socket connection."""
    if cancel and cancel.is_set():
        result["error"] = "Scan cancelled."
        return result

    logger.info(f"ClamAV: socket scan — {target}")
    start = time.monotonic()
    try:
        response = _contscan_socket(sock_path, target)
    except OSError as exc:
        result["error"] = f"Socket error: {exc}"
        return result

    if on_line:
        on_line(response)

    result["scanned"] = 1
    if "FOUND" in response:
        result["infected"] = 1
        result["infections"] = [response]

    result["duration"] = _format_duration(time.monotonic() - start)
    return result


def _scan_dir_socket(
    target: str, sock_path: str, result: dict,
    on_line: Callable | None,
    cancel: "threading.Event | None",
) -> dict:
    """Scan a directory via parallel clamd socket connections."""
    whitelist = set(get_whitelist())
    files = list(_walk_files(target, whitelist))

    if not files:
        result["duration"] = "0.000 sec (0 s)"
        return result

    logger.info(
        f"ClamAV: parallel scan — {len(files)} files, "
        f"{_PARALLEL_WORKERS} workers",
    )

    start = time.monotonic()
    scanned = 0
    infected = 0
    infections: list[str] = []

    skipped = 0
    pool = ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS)
    try:
        futures = {
            pool.submit(_contscan_socket, sock_path, f): f for f in files
        }
        for future in as_completed(futures):
            if cancel and cancel.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                result["error"] = "Scan cancelled."
                return result

            try:
                response = future.result()
            except OSError as exc:
                skipped += 1
                logger.debug(f"ClamAV: skip {futures[future]}: {exc}")
                continue

            scanned += 1
            if on_line:
                on_line(response)
            if "FOUND" in response:
                infected += 1
                infections.append(response)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if skipped:
        logger.warning(f"ClamAV: {skipped} files skipped due to errors")

    result["scanned"] = scanned
    result["infected"] = infected
    result["infections"] = infections
    result["duration"] = _format_duration(time.monotonic() - start)
    return result


def is_clamonacc_running() -> bool:
    """Check if clamonacc is running (by process name)."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "clamonacc"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_app_bundle() -> bool:
    """Return True if running inside a .app bundle."""
    return (
        ".app/Contents/MacOS" in sys.executable
        or ".app/Contents/MacOS" in os.path.abspath(sys.argv[0])
    )


def _daemons_approved() -> bool:
    """Check if ClamAV daemons are approved in Login Items via SMAppService."""
    if not _is_app_bundle():
        return False
    try:
        from ServiceManagement import SMAppService

        for plist_name in _DAEMON_PLISTS:
            try:
                service = SMAppService.daemonServiceWithPlistName_(plist_name)
                status = int(service.status())
                if status != 1:  # 1 = enabled
                    return False
            except Exception:
                return False
        return True
    except ImportError:
        return False


def has_full_disk_access() -> bool:
    """Check whether the clamonacc process has Full Disk Access.

    clamonacc requires FDA to use the Endpoint Security Framework.
    We probe by attempting to read a TCC-protected path that only
    FDA-granted processes can access.
    """
    # Quick heuristic: try reading a TCC-protected directory.
    # ~/Library/Mail is protected by FDA on macOS 10.14+.
    probe = os.path.expanduser("~/Library/Mail")
    try:
        os.listdir(probe)
        return True
    except PermissionError:
        return False
    except FileNotFoundError:
        # Mail.app never used — directory doesn't exist. Try Safari data.
        probe_alt = os.path.expanduser("~/Library/Safari")
        try:
            os.listdir(probe_alt)
            return True
        except PermissionError:
            return False
        except FileNotFoundError:
            # Neither directory exists — assume FDA is granted since we
            # can't distinguish "no dir" from "no access".
            return True


def open_fda_settings():
    """Open System Settings to the Full Disk Access pane."""
    try:
        subprocess.Popen(
            ["open", "x-apple.systempreferences:"
             "com.apple.preference.security?Privacy_AllFiles"],
        )
        logger.info("Opened System Settings — Full Disk Access")
    except Exception as exc:
        logger.error(f"Could not open FDA settings: {exc}")


def open_login_items_settings():
    """Open System Settings to the Login Items pane."""
    try:
        from ServiceManagement import SMAppService

        svc = SMAppService.daemonServiceWithPlistName_(_DAEMON_PLISTS[0])
        svc.openSystemSettingsLoginItems()
        logger.info("Opened System Settings — Login Items")
    except Exception:
        # Fallback: SMAppService API unavailable (dev mode / old macOS)
        try:
            subprocess.Popen(
                ["open", "x-apple.systempreferences:"
                 "com.apple.LoginItems-Settings.extension"],
            )
            logger.info("Opened System Settings — Login Items (fallback)")
        except Exception as exc:
            logger.error(f"Could not open Login Items settings: {exc}")


def is_clamav_installed() -> bool:
    """Return True if at least the core clamscan binary can be found."""
    return _find_binary("clamscan") is not None


def get_realtime_status() -> dict:
    """Return the real-time protection status for UI display.

    Returns dict with keys:
        installed: bool (ClamAV binaries found)
        db_present: bool (signature database exists)
        approved: bool (daemons approved in Login Items)
        fda_granted: bool (Full Disk Access available)
        clamd_running: bool
        clamonacc_running: bool
        state: one of "not_installed" | "no_database" | "approval_required"
               | "fda_required" | "protected" | "error"
    """
    installed = is_clamav_installed()
    db_present = has_database()
    clamd_ok = is_clamd_running()
    clamonacc_ok = is_clamonacc_running()

    in_bundle = _is_app_bundle()

    if in_bundle:
        approved = _daemons_approved()
        fda = has_full_disk_access()
    else:
        approved = True
        fda = True

    # Priority: not installed > no DB > approval > FDA > clamd running
    # clamonacc (real-time on-access) is optional — clamd alone is enough
    # for on-demand scanning, so we show "protected" when clamd is up.
    if not installed:
        state = "not_installed"
    elif not db_present:
        state = "no_database"
    elif not approved:
        state = "approval_required"
    elif not fda:
        state = "fda_required"
    elif clamd_ok:
        state = "protected"
    else:
        state = "error"

    return {
        "installed": installed,
        "db_present": db_present,
        "approved": approved,
        "fda_granted": fda,
        "clamd_running": clamd_ok,
        "clamonacc_running": clamonacc_ok,
        "in_bundle": in_bundle,
        "state": state,
    }


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
        logger.warning("ClamAV daemons require user approval in Login Items")


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


# ── System daemon activation ─────────────────────────────


def _app_bundle_contents() -> str | None:
    """Return the Contents/ dir of the running .app bundle, or None."""
    for base in (sys.executable, os.path.abspath(sys.argv[0])):
        idx = base.find(".app/Contents/MacOS")
        if idx != -1:
            return os.path.realpath(base[: idx + len(".app/Contents")])
    return None


def activate_system_daemons() -> tuple[bool, str]:
    """Start system-level ClamAV daemons (clamd + clamonacc).

    Uses osascript to obtain admin privileges for launchctl.
    Only works when running from the installed app bundle.
    """
    contents = _app_bundle_contents()
    if not contents:
        return False, "Real-time protection requires the installed app."

    launchd_dir = os.path.join(contents, "Library", "LaunchDaemons")
    cmds = [
        # Ensure system dirs exist
        "mkdir -p '/Library/Application Support/Resistine/clamav/log' "
        "'/Library/Application Support/Resistine/clamav/db' "
        "'/Library/Application Support/Resistine/clamav/run'",
    ]
    for plist_name in _DAEMON_PLISTS:
        label = plist_name.replace(".plist", "")
        plist_path = os.path.join(launchd_dir, plist_name)
        if not os.path.exists(plist_path):
            logger.warning(f"ClamAV: plist not found: {plist_path}")
            continue
        # kickstart if already loaded, otherwise load first
        cmds.append(
            f"launchctl kickstart -k system/{label} 2>/dev/null || "
            f"launchctl load -w '{plist_path}' 2>/dev/null || true"
        )

    script = "; ".join(cmds)
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    logger.info("ClamAV: activating system daemons via launchctl")

    try:
        result = subprocess.run(
            ["osascript", "-e",
             f'do shell script "{escaped}" with administrator privileges'],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            msg = (result.stderr or "").strip() or "Admin authentication cancelled."
            logger.error(f"ClamAV: daemon activation failed: {msg}")
            return False, msg
    except subprocess.TimeoutExpired:
        return False, "Admin authentication timed out."
    except Exception as exc:
        return False, str(exc)

    # Wait for system clamd to become responsive (up to 15s)
    for _ in range(30):
        time.sleep(0.5)
        if _ping_socket(_SYSTEM_CLAMD_SOCKET):
            logger.info("ClamAV: system clamd is now running")
            return True, "Protection activated."

    return False, "Daemons loaded but clamd not responding yet."


def deactivate_system_daemons() -> tuple[bool, str]:
    """Stop system-level ClamAV daemons. Requires admin privileges."""
    cmds = []
    for plist_name in reversed(_DAEMON_PLISTS):
        label = plist_name.replace(".plist", "")
        cmds.append(f"launchctl bootout system/{label} 2>/dev/null || true")

    script = "; ".join(cmds)
    escaped = script.replace("\\", "\\\\").replace('"', '\\"')
    logger.info("ClamAV: deactivating system daemons")

    try:
        result = subprocess.run(
            ["osascript", "-e",
             f'do shell script "{escaped}" with administrator privileges'],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, "Protection deactivated."
        return False, (result.stderr or "").strip() or "Failed."
    except Exception as exc:
        return False, str(exc)


# ── Scanning ──────────────────────────────────────────────


def scan_path(
    target: str,
    on_line: Callable | None = None,
    cancel: "threading.Event | None" = None,
    proc_ref: "list | None" = None,
) -> dict:
    """Scan a file or directory via direct clamd socket when available,
    otherwise falls back to standalone clamscan.

    Returns dict with keys: scanned, infected, infections, duration, error.
    Pass a threading.Event as *cancel* to allow early termination.
    Pass a one-element list as *proc_ref* to receive the subprocess handle
    (only populated when using clamscan fallback).
    """
    result = {
        "target": target,
        "scanned": 0,
        "infected": 0,
        "infections": [],
        "duration": "",
        "error": "",
    }

    # If clamd is running, use direct socket scanning (parallel for dirs).
    # Otherwise start clamd, or fall back to standalone clamscan.
    active_socket = _active_clamd_socket()
    if not active_socket and has_database() and _find_binary("clamd"):
        logger.info("ClamAV: clamd not running — starting it for faster scan")
        ok, msg = start_clamd()
        if ok:
            active_socket = _active_clamd_socket()
        else:
            logger.warning(f"ClamAV: could not start clamd, falling back: {msg}")

    # Direct socket scanning — parallel for directories, fast for files.
    # Bypasses the clamdscan subprocess entirely.
    if active_socket:
        if os.path.isdir(target):
            return _scan_dir_socket(
                target, active_socket, result, on_line, cancel,
            )
        return _scan_file_socket(target, active_socket, result, on_line, cancel)

    # Fallback: standalone clamscan (reloads entire signature DB each run)
    binary = _find_binary("clamscan")
    if not binary:
        result["error"] = "ClamAV not installed."
        return result

    if not has_database():
        result["error"] = "No signature database — run Update first."
        return result

    cmd = [binary, "--stdout", "--verbose", "-d", _DB_DIR, "--recursive"]
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
            env=_clamav_env(), bufsize=1,
        )
    except OSError as exc:
        result["error"] = f"Could not start ClamAV: {exc}"
        return result

    # Expose proc so callers can kill it directly (e.g. cancel button)
    if proc_ref is not None:
        proc_ref[0] = proc

    scanned_from_output = 0
    try:
        for line in proc.stdout:
            if cancel and cancel.is_set():
                proc.kill()
                proc.wait(timeout=10)
                result["error"] = "Scan cancelled."
                return result
            stripped = line.rstrip()
            if on_line:
                on_line(stripped)
            if "FOUND" in stripped:
                result["infections"].append(stripped)
                scanned_from_output += 1
            elif "OK" in stripped and ":" in stripped:
                # Lines like "/path/to/file: OK"
                scanned_from_output += 1
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

        proc.wait(timeout=30)

        rc = proc.returncode
        # clamscan: 0=clean, 1=found virus, 2=error
        # Negative = killed by signal (e.g. -9 = SIGKILL from quarantine)
        if rc is not None and rc < 0:
            sig = abs(rc)
            result["error"] = (
                f"ClamAV was killed by signal {sig}. "
                "The binary may be quarantined — run: "
                "xattr -cr scripts/build/clamav-artifacts/binaries/"
            )
        elif rc == 2 and not result["infections"]:
            result["error"] = "ClamAV encountered an error during scanning."

        # clamdscan doesn't output "Scanned files:" — derive from output lines
        if result["scanned"] == 0 and scanned_from_output > 0:
            result["scanned"] = scanned_from_output
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        result["error"] = "Scan timed out."
    except Exception as exc:
        proc.kill()
        proc.wait(timeout=5)
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


def is_path_whitelisted(path: str) -> bool:
    """Check if *path* is whitelisted or inside a whitelisted directory."""
    entries = get_whitelist()
    if not entries:
        return False
    resolved = os.path.realpath(path)
    for entry in entries:
        resolved_entry = os.path.realpath(entry)
        if resolved == resolved_entry:
            return True
        if resolved.startswith(resolved_entry + os.sep):
            return True
    return False


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
