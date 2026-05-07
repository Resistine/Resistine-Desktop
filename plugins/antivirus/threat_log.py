"""Syslog-formatted threat logger for Wazuh SIEM integration.

Writes antivirus events to a log file in RFC 3164 syslog format.
The Wazuh agent reads this file via a <localfile> entry in
ossec.conf and forwards events to the SIEM dashboard.

Log format (RFC 3164):
    MMM DD HH:MM:SS hostname resistine-av: EVENT key="value" ...

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import base64
import os
import platform
import subprocess
import threading
import time

from utils.logger import logger

_PROGRAM = "resistine-av"
_write_lock = threading.Lock()


def _log_dir() -> str:
    from plugins.antivirus.clamav_common import _LOG_DIR, _ensure_dirs

    _ensure_dirs()
    return _LOG_DIR


def get_log_path() -> str:
    """Return the threat log file path."""
    return os.path.join(_log_dir(), "threats.log")


def get_log_display() -> str:
    """Return a UI-friendly description of where threat events come from.

    Defender writes to the Windows event log, not a syslog file, so the
    file path on Mac/Linux maps to an event-channel name on Windows.
    """
    if platform.system() == "Windows":
        return "Microsoft-Windows-Windows Defender/Operational"
    return get_log_path()


def _hostname() -> str:
    return platform.node() or "localhost"


def _syslog_ts() -> str:
    """RFC 3164 timestamp: 'Apr 16 13:18:05'."""
    return time.strftime("%b %d %H:%M:%S")


def _write(line: str):
    with _write_lock:
        try:
            with open(get_log_path(), "a") as f:
                f.write(line + "\n")
        except OSError as exc:
            logger.error(f"AV: failed to write threat log: {exc}")


def _escape(v: str) -> str:
    """Escape user-controlled values for safe syslog embedding."""
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace(
        "\n", "\\n",
    ).replace("\r", "\\r")


def _fmt(event: str, **kv) -> str:
    ts = _syslog_ts()
    host = _hostname()
    fields = " ".join(f'{k}="{_escape(v)}"' for k, v in kv.items())
    return f"{ts} {host} {_PROGRAM}: {event} {fields}"


# ── Event loggers ────────────────────────────────────────


def log_threat_detected(signature: str, filepath: str):
    """Log a threat detection event."""
    _write(_fmt("THREAT_DETECTED", signature=signature, path=filepath))


def log_threat_quarantined(signature: str, filepath: str, dest: str):
    """Log a quarantine action."""
    _write(_fmt(
        "THREAT_QUARANTINED",
        signature=signature, path=filepath, dest=dest,
    ))


def log_threat_deleted(filepath: str):
    """Log permanent deletion of a quarantined file."""
    _write(_fmt("THREAT_DELETED", path=filepath))


def log_scan_complete(
    target: str, scanned: int, infected: int, duration: str,
):
    """Log a scan completion summary."""
    _write(_fmt(
        "SCAN_COMPLETE",
        target=target, scanned=str(scanned),
        infected=str(infected), duration=duration,
    ))


# ── Helpers ──────────────────────────────────────────────


def parse_infection_line(line: str) -> tuple[str, str]:
    """Parse '/path: Sig.Name FOUND' into (filepath, signature)."""
    parts = line.rsplit(":", 1)
    if len(parts) != 2:
        return line.strip(), "Unknown"
    filepath = parts[0].strip()
    sig_part = parts[1].strip()
    if sig_part.endswith(" FOUND"):
        sig_part = sig_part[:-6].strip()
    return filepath, sig_part


# ── Wazuh ossec.conf integration ─────────────────────────

_OSSEC_PATHS = {
    "Darwin": "/Library/Ossec/etc/ossec.conf",
    "Linux": "/var/ossec/etc/ossec.conf",
    "Windows": r"C:\Program Files (x86)\ossec-agent\ossec.conf",
}

_WAZUH_DIRS = {
    "Darwin": "/Library/Ossec",
    "Linux": "/var/ossec",
    "Windows": r"C:\Program Files (x86)\ossec-agent",
}


def is_wazuh_installed() -> bool:
    """Check if the Wazuh agent is installed.

    The config directory is root-only, so we check for the install
    directory rather than the config file itself.
    """
    d = _WAZUH_DIRS.get(platform.system())
    return bool(d and os.path.isdir(d))


def get_ossec_snippet() -> str:
    """Return the XML localfile block for ossec.conf."""
    return (
        "  <localfile>\n"
        "    <log_format>syslog</log_format>\n"
        f"    <location>{get_log_path()}</location>\n"
        "  </localfile>"
    )


def setup_wazuh_forwarding() -> tuple[bool, str]:
    """Add our localfile entry to ossec.conf (requires admin).

    Returns (success, message).
    """
    if not is_wazuh_installed():
        return False, "Wazuh agent not installed."

    if not is_wazuh_installed():
        return False, "Wazuh agent not installed."

    conf = _OSSEC_PATHS.get(platform.system())
    if not conf:
        return False, "Unsupported platform."

    # ossec.conf is root-only — skip unprivileged checks,
    # the privileged script validates everything itself.

    system = platform.system()
    if system == "Darwin":
        return _inject_darwin(conf)
    if system == "Linux":
        return _inject_linux(conf)
    if system == "Windows":
        return _inject_windows()
    return False, f"Unknown platform: {system}"


def _inject_darwin(conf: str) -> tuple[bool, str]:
    """Inject localfile entry via osascript with admin privileges."""
    snippet = get_ossec_snippet()

    # Python script runs as root: validate, backup, read, check, modify, write
    py_script = (
        "import os, shutil, sys\n"
        f"conf = {conf!r}\n"
        "if not os.path.isfile(conf):\n"
        "    print('error: ossec.conf not found at ' + conf)\n"
        "    sys.exit(1)\n"
        "with open(conf) as f:\n"
        "    content = f.read()\n"
        "if 'threats.log' in content:\n"
        "    print('already_configured')\n"
        "    sys.exit(0)\n"
        "shutil.copy2(conf, conf + '.bak')\n"
        f"snippet = {snippet!r}\n"
        "new = content.replace("
        "'</ossec_config>', snippet + '\\n\\n</ossec_config>')\n"
        "with open(conf, 'w') as f:\n"
        "    f.write(new)\n"
        "print('configured')\n"
    )
    encoded = base64.b64encode(py_script.encode()).decode()

    shell_cmd = (
        f"printf '%s' '{encoded}' | base64 -d | python3 && "
        f"launchctl kickstart -k system/com.wazuh.agent 2>/dev/null; true"
    )
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    apple_script = (
        f'do shell script "{escaped}" with administrator privileges'
    )

    try:
        result = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if "already_configured" in output:
                return True, "Already configured."
            logger.info("AV: Wazuh forwarding configured")
            return True, "Configured. Wazuh agent restarted."
        err = result.stderr.strip()
        if "User cancelled" in err or "(-128)" in err:
            return False, "Admin approval cancelled."
        return False, err or "Failed to update ossec.conf"
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for admin approval."
    except Exception as exc:
        return False, str(exc)


def _inject_linux(conf: str) -> tuple[bool, str]:
    """Inject localfile entry via pkexec/sudo."""
    snippet = get_ossec_snippet()

    py_script = (
        "import os, shutil, sys\n"
        f"conf = {conf!r}\n"
        "if not os.path.isfile(conf):\n"
        "    print('error: ossec.conf not found at ' + conf)\n"
        "    sys.exit(1)\n"
        "with open(conf) as f:\n"
        "    content = f.read()\n"
        "if 'threats.log' in content:\n"
        "    print('already_configured')\n"
        "    sys.exit(0)\n"
        "shutil.copy2(conf, conf + '.bak')\n"
        f"snippet = {snippet!r}\n"
        "new = content.replace("
        "'</ossec_config>', snippet + '\\n\\n</ossec_config>')\n"
        "with open(conf, 'w') as f:\n"
        "    f.write(new)\n"
        "print('configured')\n"
    )
    encoded = base64.b64encode(py_script.encode()).decode()
    shell_cmd = (
        f"printf '%s' '{encoded}' | base64 -d | python3 && "
        f"systemctl restart wazuh-agent 2>/dev/null; true"
    )

    for cmd in (
        ["pkexec", "bash", "-c", shell_cmd],
        ["sudo", "bash", "-c", shell_cmd],
    ):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if "already_configured" in output:
                    return True, "Already configured."
                logger.info("AV: Wazuh forwarding configured")
                return True, "Configured. Wazuh agent restarted."
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        except Exception as exc:
            return False, str(exc)
    return False, "Could not obtain admin privileges."


def _inject_windows() -> tuple[bool, str]:
    """Register the Windows Defender event channel with the Wazuh agent.

    Defender writes to Microsoft-Windows-Windows Defender/Operational, which
    the Wazuh agent reads directly via an <eventchannel> localfile entry — no
    syslog file needed (unlike the ClamAV path used on Mac/Linux).
    """
    from plugins.wazuh.agent.wazuh_functions_windows import inject_defender_config

    try:
        ok = inject_defender_config()
    except Exception as exc:
        return False, str(exc)
    if ok:
        return True, "Configured. Defender events will forward to Wazuh."
    return False, "Failed to update ossec.conf. See logs for details."
