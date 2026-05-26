"""ClamAV platform module — macOS (Darwin).

Binary discovery, daemon registration (SMAppService / launchd),
Full Disk Access checks, and library path setup for macOS.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from utils.logger import logger


def _applescript_quote(s: str) -> str:
    """Quote a string for AppleScript (double-quote delimited)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ── macOS-specific paths ──────────────────────────────────

_SYSTEM_CLAMAV_DIR = "/Library/Application Support/Resistine/clamav"
_SYSTEM_CLAMD_SOCKET = os.path.join(_SYSTEM_CLAMAV_DIR, "run", "clamd.sock")
_SYSTEM_CLAMD_CONF = os.path.join(_SYSTEM_CLAMAV_DIR, "clamd.conf")
_SYSTEM_FRESHCLAM_CONF = os.path.join(_SYSTEM_CLAMAV_DIR, "freshclam.conf")
_SYSTEM_DB_DIR = os.path.join(_SYSTEM_CLAMAV_DIR, "db")
_SYSTEM_LOG_DIR = os.path.join(_SYSTEM_CLAMAV_DIR, "log")
_SYSTEM_RUN_DIR = os.path.join(_SYSTEM_CLAMAV_DIR, "run")

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
]

# Legacy SMAppService labels from ≤4.12 — these were renamed to
# com.resistine.desktop.* in 2026-04-14 (commit 57aa3dd). Users updating
# from 4.12 still have the old labels registered in launchd, which fight
# the new labels over the same Unix socket and cause clamd crash loops.
# Bootout cleans them out regardless of plist file presence.
_LEGACY_DAEMON_LABELS = [
    "com.resistine.clamd",
    "com.resistine.clamonacc",
]

# Paths derived from the project source tree (relative to this file).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DEV_ARTIFACTS = os.path.join(
    _PROJECT_ROOT, "scripts", "build", "clamav-artifacts",
)


def _installed_app_contents() -> str | None:
    """Find an installed Resistine.app's Contents/ directory.

    Checks standard macOS application directories rather than assuming
    a single hardcoded path, so it works on any machine.
    """
    for app_dir in ("/Applications", os.path.expanduser("~/Applications")):
        contents = os.path.join(app_dir, "Resistine.app", "Contents")
        if os.path.isdir(contents):
            return contents
    return None


# ── Platform interface ────────────────────────────────────


def system_clamd_socket_path() -> str:
    """Return the system-level clamd socket path."""
    return _SYSTEM_CLAMD_SOCKET


def system_clamd_conf_path() -> str:
    """Return the system-level clamd.conf location."""
    return _SYSTEM_CLAMD_CONF


def system_db_dir() -> str | None:
    """Return system DB dir path if it exists, else None."""
    if os.path.isdir(_SYSTEM_DB_DIR):
        return _SYSTEM_DB_DIR
    return None


def system_db_dir_writable() -> str | None:
    """Return system DB dir if writable by the current user, else None."""
    if os.path.isdir(_SYSTEM_DB_DIR) and os.access(_SYSTEM_DB_DIR, os.W_OK):
        return _SYSTEM_DB_DIR
    return None


def find_binary(name: str) -> str | None:
    """Find a ClamAV binary: running bundle -> installed app -> dev artifacts -> PATH."""
    candidates = []

    # 1. Running app bundle (frozen build — works regardless of install location)
    contents = _app_bundle_contents()
    if contents:
        candidates.append(os.path.join(contents, "Helpers", name))

    # 2. Installed app bundle (for dev mode using signed binaries)
    installed = _installed_app_contents()
    if installed:
        candidates.append(os.path.join(installed, "Helpers", name))

    # 3. Dev build artifacts
    candidates.append(os.path.join(_DEV_ARTIFACTS, "binaries", name))

    for path in candidates:
        resolved = os.path.realpath(path)
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved

    # 4. System PATH
    return shutil.which(name)


def find_certs_dir() -> str | None:
    """Locate the ClamAV CVD signature-verification certs directory."""
    candidates = []

    # 1. Running app bundle (frozen build — works regardless of install location)
    contents = _app_bundle_contents()
    if contents:
        candidates.append(os.path.join(contents, "certs"))

    # 2. Installed app bundle
    installed = _installed_app_contents()
    if installed:
        candidates.append(os.path.join(installed, "certs"))

    # 3. Dev build artifacts
    candidates.append(os.path.join(_DEV_ARTIFACTS, "certs"))

    # 4. ClamAV-Mac sibling repo (dev convenience — checked out alongside)
    clamav_sibling = os.path.join(_PROJECT_ROOT, "..", "ClamAV-Mac")
    candidates.append(os.path.join(clamav_sibling, "install", "etc", "certs"))
    candidates.append(os.path.join(clamav_sibling, "certs"))

    for path in candidates:
        resolved = os.path.realpath(path)
        if os.path.isdir(resolved) and os.path.isfile(
            os.path.join(resolved, "clamav.crt"),
        ):
            return resolved
    return None


def clamav_env() -> dict[str, str]:
    """Return env dict with library paths, SSL certs, and CVD certs for ClamAV."""
    env = os.environ.copy()

    # Override the CVD signature-verification certs directory.
    if "CVD_CERTS_DIR" not in env:
        certs_dir = find_certs_dir()
        if certs_dir:
            env["CVD_CERTS_DIR"] = certs_dir

    # Point OpenSSL at the system CA bundle so freshclam can verify TLS.
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
        installed = _installed_app_contents()
        if installed:
            fw = os.path.join(installed, "Frameworks")
            if os.path.isdir(fw):
                lib_dirs.append(fw)
        # Dev build artifacts
        lib_dir = os.path.join(_DEV_ARTIFACTS, "lib")
        if os.path.isdir(lib_dir):
            lib_dirs.append(lib_dir)
        if lib_dirs:
            existing = env.get("DYLD_LIBRARY_PATH", "")
            combined = ":".join(lib_dirs)
            env["DYLD_LIBRARY_PATH"] = (
                f"{combined}:{existing}" if existing else combined
            )
    return env


def is_app_bundle() -> bool:
    """Return True if running inside a .app bundle."""
    return (
        ".app/Contents/MacOS" in sys.executable
        or ".app/Contents/MacOS" in os.path.abspath(sys.argv[0])
    )


def daemons_approved() -> bool:
    """Check if ClamAV daemons are approved in Login Items via SMAppService."""
    if not is_app_bundle():
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
    """Check whether clamonacc has Full Disk Access.

    clamonacc requires FDA for the Endpoint Security Framework.
    Rather than probing TCC-protected paths (which checks *our* process,
    not clamonacc's), we check clamonacc's actual runtime state:

    - If clamonacc is running → FDA is granted (it would crash without it).
    - If the system daemon is loaded but clamonacc isn't running → it's
      crash-looping, which means FDA (or ESF entitlement) is missing.
    - If the daemon isn't loaded yet → we can't tell, so fall back to a
      TCC directory probe as a best-effort hint.
    """
    # Direct check: if clamonacc is alive, it has FDA.
    if is_clamonacc_running():
        return True

    # If the launchd job is loaded AND the system config exists (meaning
    # activate_system_daemons has been run), a crash-looping clamonacc
    # indicates missing FDA. Without the config, clamonacc crashes because
    # it can't find its config file — not because of FDA.
    #
    # IMPORTANT: only blame FDA if system clamd is actually running.
    # clamonacc depends on clamd's socket — if clamd is still loading its
    # 500 MB+ signature DB, clamonacc will restart repeatedly trying to
    # connect. That's a transient startup issue, not an FDA denial.
    if os.path.exists(_SYSTEM_CLAMD_CONF):
        from plugins.antivirus.clamav_common import _ping_socket

        try:
            result = subprocess.run(
                ["launchctl", "print",
                 "system/com.resistine.desktop.clamonacc"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout
                for line in output.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("runs = "):
                        try:
                            runs = int(stripped.split("=")[1].strip())
                            if runs > 3:
                                if _ping_socket(_SYSTEM_CLAMD_SOCKET):
                                    # clamd is ready but clamonacc has
                                    # crashed multiple times. Could be a
                                    # genuine FDA issue OR a transient
                                    # startup race (clamonacc couldn't
                                    # connect while clamd was loading
                                    # signatures). Poll for up to 12s
                                    # (covers the 10s ThrottleInterval
                                    # in the clamonacc launchd plist)
                                    # for launchd to restart it.
                                    for _retry in range(24):
                                        time.sleep(0.5)
                                        if is_clamonacc_running():
                                            logger.debug(
                                                "FDA check: clamonacc "
                                                "recovered — FDA is OK",
                                            )
                                            return True
                                    logger.debug(
                                        f"FDA check: clamonacc crash-looping "
                                        f"({runs} runs) with clamd running"
                                        f" — likely missing FDA",
                                    )
                                    return False
                                logger.debug(
                                    f"FDA check: clamonacc restarting "
                                    f"({runs} runs) but clamd not ready "
                                    f"— not an FDA issue",
                                )
                        except ValueError:
                            pass
        except Exception:
            pass

    # Final check: clamonacc may have started between the early-return
    # check and the crash-loop analysis above.
    if is_clamonacc_running():
        return True

    # Fallback: probe a TCC-protected directory as a hint.
    # This checks *our* process, not clamonacc, but is a reasonable
    # proxy when the daemon hasn't been loaded yet.
    probes = [
        os.path.expanduser("~/Library/Mail"),
        os.path.expanduser("~/Library/Safari"),
        os.path.expanduser("~/Library/Cookies"),
    ]
    for probe in probes:
        try:
            os.listdir(probe)
            return True
        except PermissionError:
            return False
        except FileNotFoundError:
            continue

    # When we can't determine FDA status (no TCC-protected dirs found),
    # assume it's available. If clamonacc actually lacks FDA, the
    # crash-loop check will catch it definitively once daemons are loaded.
    # Defaulting to False here causes a premature "FDA Required" screen
    # before the user has even started protection.
    logger.debug("FDA check: cannot determine status, assuming granted")
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
        try:
            subprocess.Popen(
                ["open", "x-apple.systempreferences:"
                 "com.apple.LoginItems-Settings.extension"],
            )
            logger.info("Opened System Settings — Login Items (fallback)")
        except Exception as exc:
            logger.error(f"Could not open Login Items settings: {exc}")


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


def _legacy_labels_loaded() -> list[str]:
    """Return any legacy daemon labels still loaded in system launchd.

    Reads `launchctl print system` (no sudo needed for read) and matches
    against _LEGACY_DAEMON_LABELS. Used to gate the sudo prompt so users
    on a clean install never see it.
    """
    try:
        result = subprocess.run(
            ["launchctl", "print", "system"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    # launchctl print system emits labels in two formats we care about:
    #   "com.resistine.clamd" => enabled    (services listing)
    #   70165\t1\tcom.resistine.clamd       (process table)
    # Allow whitespace, slash, or quote on either side so both match;
    # the boundary still prevents substring false-positives.
    found = []
    for label in _LEGACY_DAEMON_LABELS:
        pattern = re.compile(
            rf'(?:^|[\s"/]){re.escape(label)}(?:[\s"/]|$)', re.MULTILINE,
        )
        if pattern.search(result.stdout):
            found.append(label)
    return found


def _cleanup_legacy_plists():
    """Remove old plists and unregister stale SMAppService labels.

    Covers two migration paths:
    1. Pre-SMAppService installs that dropped plists in /Library/LaunchDaemons/
    2. ≤4.12 SMAppService installs using the old com.resistine.{clamd,clamonacc}
       labels (renamed to com.resistine.desktop.* in commit 57aa3dd).
    Both leave residue that fights the current daemons over the clamd
    socket and causes crash loops.
    """
    found_paths = [p for p in _LEGACY_PLIST_PATHS if os.path.exists(p)]
    loaded_labels = _legacy_labels_loaded()
    if not found_paths and not loaded_labels:
        return

    cmds = []
    # Bootout legacy labels first so they release the socket before
    # the new daemons try to claim it.
    for label in loaded_labels:
        cmds.append(
            f"launchctl bootout system/{shlex.quote(label)} 2>/dev/null",
        )
    for plist in found_paths:
        quoted = shlex.quote(plist)
        cmds.append(f"launchctl bootout system {quoted} 2>/dev/null")
        cmds.append(f"rm -f {quoted}")
    # Clear the stale socket/pid so the new clamd has a clean slate.
    sock = shlex.quote(_SYSTEM_RUN_DIR + "/clamd.sock")
    pid = shlex.quote(_SYSTEM_RUN_DIR + "/clamd.pid")
    cmds.append(f"rm -f {sock} {pid}")

    script = "; ".join(cmds)
    try:
        subprocess.run(
            [
                "osascript", "-e",
                "do shell script " + _applescript_quote(script)
                + " with administrator privileges",
            ],
            capture_output=True, text=True, timeout=30,
        )
        logger.info(
            f"Cleaned up legacy ClamAV state — "
            f"labels: {loaded_labels}, plists: {found_paths}",
        )
    except Exception as e:
        logger.warning(f"Could not clean up legacy ClamAV state: {e}")


# ── System daemon activation ─────────────────────────────


def _app_bundle_contents() -> str | None:
    """Return the Contents/ dir of the running .app bundle, or None."""
    for base in (sys.executable, os.path.abspath(sys.argv[0])):
        idx = base.find(".app/Contents/MacOS")
        if idx != -1:
            return os.path.realpath(base[: idx + len(".app/Contents")])
    return None


def _generate_system_clamd_conf() -> str:
    """Generate clamd.conf content for the system-level daemon.

    This config is shared by clamd AND clamonacc (which reads it via
    ``--config-file``).  The OnAccess* directives are required for
    clamonacc's real-time ESF monitoring — without OnAccessIncludePath
    clamonacc exits with "No OnAccessIncludePath configured".
    """
    import tempfile

    return (
        "# Auto-generated by Resistine — do not edit manually\n"
        f"LocalSocket {_SYSTEM_CLAMD_SOCKET}\n"
        f"PidFile {_SYSTEM_RUN_DIR}/clamd.pid\n"
        f"DatabaseDirectory {_SYSTEM_DB_DIR}\n"
        f"LogFile {_SYSTEM_LOG_DIR}/clamd.log\n"
        "LogFileMaxSize 5M\n"
        "LogTime yes\n"
        "LogVerbose yes\n"
        "LogClean yes\n"
        "MaxThreads 8\n"
        f"TemporaryDirectory {tempfile.gettempdir()}\n"
        "MaxDirectoryRecursion 20\n"
        "FollowDirectorySymlinks yes\n"
        "SelfCheck 60\n"
        "ExcludePath ^/proc\n"
        "ExcludePath ^/sys\n"
        "ExcludePath ^/dev\n"
        "\n"
        "# On-access real-time monitoring (clamonacc via ESF)\n"
        "OnAccessIncludePath /Users\n"
        "OnAccessIncludePath /Applications\n"
        "OnAccessIncludePath /private/tmp\n"
        f"OnAccessExcludePath {_SYSTEM_CLAMAV_DIR}\n"
        "OnAccessPrevention no\n"
        "OnAccessExtraScanning yes\n"
        "OnAccessMaxFileSize 50M\n"
    )


def _generate_system_freshclam_conf() -> str:
    """Generate freshclam.conf content for system-level DB updates."""
    conf = (
        "# Auto-generated by Resistine — do not edit manually\n"
        f"DatabaseDirectory {_SYSTEM_DB_DIR}\n"
        f"UpdateLogFile {_SYSTEM_LOG_DIR}/freshclam.log\n"
        "LogFileMaxSize 2M\n"
        "LogTime yes\n"
        "DatabaseMirror database.clamav.net\n"
        f"NotifyClamd {_SYSTEM_CLAMD_CONF}\n"
    )
    certs_dir = find_certs_dir()
    if certs_dir:
        conf += f"CVDCertsDirectory {certs_dir}\n"
    return conf


def activate_system_daemons() -> tuple[bool, str]:
    """Set up and start system-level ClamAV daemons (clamd + clamonacc).

    One admin prompt covers the full setup:
      1. Create system directories
      2. Write system-level clamd.conf and freshclam.conf
      3. Make DB dir writable by the current user (for freshclam updates)
      4. Download initial signature DB if none exists
      5. Load/restart daemons via launchctl

    Only works when running from the installed app bundle.
    """
    contents = _app_bundle_contents()
    if not contents:
        return False, "Real-time protection requires the installed app."

    launchd_dir = os.path.join(contents, "Library", "LaunchDaemons")

    # Generate config content
    import base64

    clamd_conf_b64 = base64.b64encode(
        _generate_system_clamd_conf().encode(),
    ).decode()
    freshclam_conf_b64 = base64.b64encode(
        _generate_system_freshclam_conf().encode(),
    ).decode()

    sys_dirs = [_SYSTEM_LOG_DIR, _SYSTEM_DB_DIR, _SYSTEM_RUN_DIR]
    db_dir_q = shlex.quote(_SYSTEM_DB_DIR)
    conf_q = shlex.quote(_SYSTEM_CLAMD_CONF)
    fconf_q = shlex.quote(_SYSTEM_FRESHCLAM_CONF)

    cmds = [
        # Resolve console user with fallback
        "CUSER=$(stat -f '%Su' /dev/console 2>/dev/null || echo root)",
        # 1. Create directories
        "mkdir -p " + " ".join(shlex.quote(d) for d in sys_dirs),
        # 2. Write system-level configs (base64 avoids quoting issues)
        f"echo {shlex.quote(clamd_conf_b64)} | base64 -D > {conf_q}",
        f"echo {shlex.quote(freshclam_conf_b64)} | base64 -D > {fconf_q}",
        # 3. Make DB dir + config files writable by console user so
        #    freshclam and post-update config refresh work without admin
        f"chown $CUSER:staff {db_dir_q} {conf_q} {fconf_q}",
        f"chmod 775 {db_dir_q}",
    ]

    # 4. Seed the system DB directory if empty.
    #    Try freshclam first; if that fails (network/certs), fall back to
    #    copying the user-level DB files that were already downloaded via
    #    the "Update Now" button.  Without a DB, clamd won't start.
    freshclam_bin = find_binary("freshclam")
    certs_dir = find_certs_dir()

    from plugins.antivirus.clamav_common import _DB_DIR as _user_db_dir

    user_db_q = shlex.quote(_user_db_dir)

    if freshclam_bin:
        env_prefix = ""
        if certs_dir:
            env_prefix = f"CVD_CERTS_DIR={shlex.quote(certs_dir)} "
        cmds.append(
            f"if ! ls {db_dir_q}/*.cvd 1>/dev/null 2>&1; then "
            f"{env_prefix}"
            f"{shlex.quote(freshclam_bin)} "
            f"--config-file {fconf_q} --stdout 2>&1 || true; fi",
        )

    # Fallback: copy user-level DB files if freshclam didn't populate
    # the system dir (e.g. network down, certs issue).
    cmds.append(
        f"if ! ls {db_dir_q}/*.cvd 1>/dev/null 2>&1 "
        f"&& ls {user_db_q}/*.cvd 1>/dev/null 2>&1; then "
        f"cp {user_db_q}/*.cvd {db_dir_q}/ 2>/dev/null || true; "
        f"cp {user_db_q}/*.cld {db_dir_q}/ 2>/dev/null || true; "
        f"chown $CUSER:staff {db_dir_q}/*.cvd {db_dir_q}/*.cld "
        f"2>/dev/null || true; fi",
    )

    # 5. Load / restart daemons
    for plist_name in _DAEMON_PLISTS:
        label = plist_name.replace(".plist", "")
        plist_path = os.path.join(launchd_dir, plist_name)
        if not os.path.exists(plist_path):
            logger.warning(f"ClamAV: plist not found: {plist_path}")
            continue
        quoted_path = shlex.quote(plist_path)
        cmds.append(
            f"launchctl kickstart -k system/{label} 2>/dev/null || "
            f"launchctl load -w {quoted_path} 2>/dev/null || true",
        )

    script = "; ".join(cmds)
    logger.info("ClamAV: activating system daemons via launchctl")

    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                "do shell script " + _applescript_quote(script)
                + " with administrator privileges",
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            msg = (result.stderr or "").strip() or "Admin authentication cancelled."
            logger.error(f"ClamAV: daemon activation failed: {msg}")
            return False, msg
    except subprocess.TimeoutExpired:
        return False, "Setup timed out — try again or check network for DB download."
    except Exception as exc:
        return False, str(exc)

    # Verify daemons actually launched before waiting for the socket.
    # clamd takes a while to load the ~500 MB signature DB, but we can
    # confirm the process is alive almost immediately.
    from plugins.antivirus.clamav_common import _ping_socket

    def _clamd_process_alive() -> bool:
        """Check if the system clamd process is running."""
        try:
            r = subprocess.run(
                ["launchctl", "print", "system/com.resistine.desktop.clamd"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                return False
            # Look for "pid = <number>" in launchctl output
            for ln in r.stdout.splitlines():
                if ln.strip().startswith("pid = "):
                    try:
                        return int(ln.strip().split("=")[1].strip()) > 0
                    except ValueError:
                        pass
            return False
        except Exception:
            return False

    def _clamonacc_process_alive() -> bool:
        """Check if clamonacc process is running."""
        try:
            r = subprocess.run(
                ["pgrep", "-x", "clamonacc"],
                capture_output=True, timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

    # Give daemons a moment to launch, then verify they're alive
    time.sleep(2)

    if not _clamd_process_alive():
        logger.error("ClamAV: clamd process did not start")
        return False, "clamd failed to start — check system logs."

    # clamd is alive — wait up to 30s for it to become responsive
    # (loading signature DB). This is a reasonable balance between
    # giving feedback quickly and confirming it actually works.
    for _ in range(60):
        time.sleep(0.5)
        if _ping_socket(_SYSTEM_CLAMD_SOCKET):
            logger.info("ClamAV: system clamd is now running")
            # Wait for clamonacc to stabilize now that clamd is ready.
            # clamonacc may have crash-looped while clamd was loading
            # its 500 MB+ signature DB. The launchd plist has a 10s
            # ThrottleInterval, so we need to wait long enough for
            # launchd to schedule the next restart after the throttle.
            for _w in range(30):  # ~15 seconds (covers 10s throttle)
                if _clamonacc_process_alive():
                    logger.info("ClamAV: clamonacc is running")
                    break
                time.sleep(0.5)
            else:
                logger.warning(
                    "ClamAV: clamonacc not running after activation "
                    "— Full Disk Access may be needed",
                )
            return True, "Protection activated."

    # clamd process is alive but not responding after 30s — it's still
    # loading signatures. Return success; the status poll will detect
    # when it's ready.
    logger.info("ClamAV: clamd alive but still loading signatures")
    return True, "Protection starting — signatures loading in background."


def deactivate_system_daemons() -> tuple[bool, str]:
    """Stop system-level ClamAV daemons. Requires admin privileges."""
    cmds = []
    for plist_name in reversed(_DAEMON_PLISTS):
        label = plist_name.replace(".plist", "")
        cmds.append(f"launchctl bootout system/{label} 2>/dev/null || true")
    # Also bootout legacy labels and remove their plists in case the user
    # is uninstalling after an incomplete migration from ≤4.12 — leaves
    # no orphaned daemons or plist files behind.
    for label in _LEGACY_DAEMON_LABELS:
        cmds.append(f"launchctl bootout system/{label} 2>/dev/null || true")
    for plist in _LEGACY_PLIST_PATHS:
        cmds.append(f"rm -f {shlex.quote(plist)}")

    script = "; ".join(cmds)
    logger.info("ClamAV: deactivating system daemons")

    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                "do shell script " + _applescript_quote(script)
                + " with administrator privileges",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, "Protection deactivated."
        return False, (result.stderr or "").strip() or "Failed."
    except Exception as exc:
        return False, str(exc)


def refresh_system_configs():
    """Rewrite system-level ClamAV configs if the DB dir is writable.

    Called after a Sparkle update to ensure configs reflect the current
    app bundle (e.g. updated CVDCertsDirectory path).  Only rewrites
    files the current user can write — no admin prompt.
    """
    if not os.path.isdir(_SYSTEM_CLAMAV_DIR):
        return  # System not set up yet

    for path, content in (
        (_SYSTEM_CLAMD_CONF, _generate_system_clamd_conf()),
        (_SYSTEM_FRESHCLAM_CONF, _generate_system_freshclam_conf()),
    ):
        try:
            with open(path, "w") as f:
                f.write(content)
            logger.debug(f"ClamAV: refreshed {os.path.basename(path)}")
        except PermissionError:
            logger.debug(f"ClamAV: cannot refresh {path} (permission denied)")
