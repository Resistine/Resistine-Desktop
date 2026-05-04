"""Windows Defender backend for the antivirus plugin.

Provides the same public surface as plugins.antivirus.clamav_common
(scan_path, run_freshclam, get_realtime_status, list_quarantined, etc.)
backed by Windows Defender via PowerShell cmdlets:
  Get-MpComputerStatus, Start-MpScan, Get-MpThreatDetection,
  Update-MpSignature, Set-MpPreference, Remove-MpThreat.

File-based bookkeeping (whitelist + scan-exclusion JSON) is shared with
the ClamAV backend by re-exporting from clamav_common — those helpers
are pure file ops with no engine-specific dependency.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

from utils.logger import logger

# ── Shared file-based bookkeeping ─────────────────────────
# Whitelist and scan-exclusion settings are user-level config, identical
# across engines. Re-exported so plugins.antivirus.clamav.* still resolves.
from plugins.antivirus.clamav_common import (  # noqa: F401
    _CLAMAV_DATA_DIR,
    _CLAMD_CONF,
    _CLAMD_PID,
    _CLAMD_SOCKET,
    _DB_DIR,
    _EXCLUSIONS_FILE,
    _FRESHCLAM_CONF,
    _LOG_DIR,
    _PARALLEL_WORKERS,
    _QUARANTINE_DIR,
    _RUN_DIR,
    _SKIP_DIRS,
    _WHITELIST_FILE,
    _ensure_dirs,
    _format_duration,
    _walk_files,
    add_excluded_extension,
    add_excluded_extensions,
    add_to_whitelist,
    ensure_config,
    get_scan_exclusions,
    get_whitelist,
    is_path_whitelisted,
    remove_excluded_extension,
    remove_from_whitelist,
    set_max_file_size,
    set_scan_exclusions,
)


_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW — keep PowerShell windows hidden


# ── PowerShell helpers ─────────────────────────────────────


def _ps(command: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a PowerShell command, return (rc, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except FileNotFoundError:
        return -1, "", "powershell not found"
    except Exception as exc:
        return -1, "", str(exc)


def _mp_status() -> dict:
    """Return a parsed Get-MpComputerStatus snapshot, or {} on failure."""
    rc, out, _ = _ps(
        "Get-MpComputerStatus | Select-Object "
        "AntivirusEnabled, RealTimeProtectionEnabled, "
        "AntivirusSignatureLastUpdated, AntivirusSignatureVersion, "
        "AMServiceEnabled "
        "| ConvertTo-Json -Compress",
        timeout=15,
    )
    if rc != 0 or not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


def _parse_mp_date(value) -> float | None:
    """Best-effort parse of Defender's date field into epoch seconds."""
    if not isinstance(value, str):
        return None
    if value.startswith("/Date(") and value.endswith(")/"):
        try:
            ms_part = value[6:-2]
            for sep in ("+", "-"):
                if sep in ms_part[1:]:
                    ms_part = ms_part.split(sep, 1)[0]
                    break
            return int(ms_part) / 1000.0
        except ValueError:
            return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


# ── Engine identity ──────────────────────────────────────


def engine_name() -> str:
    """Override clamav_common's "ClamAV" with Windows Defender."""
    return "Windows Defender"


# ── Status / availability ─────────────────────────────────


def is_available() -> bool:
    """True if Defender is installed and responsive on this machine."""
    return bool(_mp_status())


def is_clamav_installed() -> bool:
    """Alias kept for interface parity — Defender is the AV engine here."""
    return is_available()


def is_clamd_running() -> bool:
    """True if Defender's real-time protection service is active."""
    return bool(_mp_status().get("RealTimeProtectionEnabled"))


def has_database() -> bool:
    """True if Defender reports a non-empty signature version."""
    return bool(_mp_status().get("AntivirusSignatureVersion"))


def get_db_info() -> dict[str, str]:
    """Return signature version + last-updated timestamp for the UI."""
    info = {"signatures": "—", "last_updated": "—"}
    s = _mp_status()
    ver = s.get("AntivirusSignatureVersion")
    if ver:
        info["signatures"] = str(ver)
    ts = _parse_mp_date(s.get("AntivirusSignatureLastUpdated"))
    if ts:
        info["last_updated"] = time.strftime(
            "%Y-%m-%d %H:%M", time.localtime(ts),
        )
    return info


def get_realtime_status() -> dict:
    """Match the schema of clamav_common.get_realtime_status."""
    s = _mp_status()
    installed = bool(s)
    db_present = bool(s.get("AntivirusSignatureVersion"))
    rt_enabled = bool(s.get("RealTimeProtectionEnabled"))

    if not installed:
        state = "not_installed"
    elif not db_present:
        state = "no_database"
    elif rt_enabled:
        state = "protected"
    else:
        state = "error"

    return {
        "installed": installed,
        "db_present": db_present,
        "approved": True,
        "fda_granted": True,
        "clamd_running": rt_enabled,
        "clamonacc_running": rt_enabled,
        "system_clamd_running": rt_enabled,
        "in_bundle": False,
        "state": state,
    }


# ── Daemon lifecycle ───────────────────────────────────────


def start_clamd() -> tuple[bool, str]:
    """Defender's RT service is OS-managed — nothing to start."""
    return True, "Defender is managed by Windows."


def stop_clamd() -> tuple[bool, str]:
    return True, "Defender is managed by Windows."


def activate_system_daemons() -> tuple[bool, str]:
    """Enable Defender real-time protection (requires admin)."""
    rc, _, err = _ps(
        "Set-MpPreference -DisableRealtimeMonitoring $false",
        timeout=15,
    )
    if rc == 0:
        return True, "Real-time protection enabled."
    return False, err or "Failed to enable real-time protection."


def deactivate_system_daemons() -> tuple[bool, str]:
    """Disable Defender real-time protection (requires admin)."""
    rc, _, err = _ps(
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        timeout=15,
    )
    if rc == 0:
        return True, "Real-time protection disabled."
    return False, err or "Failed to disable real-time protection."


def ensure_daemons_registered():
    """No-op — Defender ships with Windows."""


def refresh_system_configs():
    """No-op — no Resistine-managed system configs on Windows."""


# ── Signature updates ─────────────────────────────────────


def run_freshclam(on_line: Callable | None = None) -> tuple[bool, str]:
    """Refresh Defender's signature database via Update-MpSignature."""
    if on_line:
        on_line("Updating Windows Defender signatures...")
    rc, out, err = _ps("Update-MpSignature", timeout=300)
    if rc == 0:
        return True, "Signatures updated successfully."
    return False, err or out or f"Update-MpSignature exited with code {rc}"


# ── Scanning ──────────────────────────────────────────────


def scan_path(
    target: str,
    on_line: Callable | None = None,
    cancel: "threading.Event | None" = None,
    proc_ref: "list | None" = None,
    on_total: Callable | None = None,
) -> dict:
    """Scan a file or directory via Start-MpScan -ScanType CustomScan.

    Defender doesn't emit a per-file stream like clamscan, so:
      - on_total is reported as 1 (we treat the whole scan as one unit)
      - on_line gets a start message and a per-detection summary at the end
      - infections come from Get-MpThreatDetection deltas
    """
    result = {
        "target": target,
        "scanned": 0,
        "infected": 0,
        "infections": [],
        "duration": "",
        "error": "",
    }

    if not is_available():
        result["error"] = "Windows Defender is not available."
        return result

    if on_total:
        on_total(1)

    pre_ids = _detection_ids()

    target_q = target.replace("'", "''")
    cmd = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        f"Start-MpScan -ScanType CustomScan -ScanPath '{target_q}'"
    )

    if on_line:
        on_line(f"Scanning {target} with Windows Defender...")

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", cmd],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=_NO_WINDOW,
        )
    except Exception as exc:
        result["error"] = f"Could not start Defender scan: {exc}"
        return result

    if proc_ref is not None:
        proc_ref[0] = proc

    try:
        while proc.poll() is None:
            if cancel and cancel.is_set():
                proc.kill()
                proc.wait(timeout=5)
                result["error"] = "Scan cancelled."
                return result
            time.sleep(0.5)
        proc.wait(timeout=5)
    except Exception as exc:
        try:
            proc.kill()
        except OSError:
            pass
        result["error"] = str(exc)
        return result

    new_detections = [
        d for d in _list_detections() if d.get("id") not in pre_ids
    ]
    infections = [
        f"{d.get('resource', target)}: {d.get('name', 'Unknown')} FOUND"
        for d in new_detections
    ]
    if on_line:
        for line in infections:
            on_line(line)
        on_line(f"Scan complete: {len(infections)} threat(s) detected.")

    result["scanned"] = 1
    result["infected"] = len(infections)
    result["infections"] = infections
    result["duration"] = _format_duration(time.monotonic() - start)
    if proc.returncode not in (0, None) and not infections:
        logger.debug(f"Defender: Start-MpScan rc={proc.returncode}")
    return result


# ── Quarantine ────────────────────────────────────────────


def _list_detections() -> list[dict]:
    """Return Defender's current threat detections as normalized dicts."""
    rc, out, _ = _ps(
        "Get-MpThreatDetection | Select-Object DetectionID, ThreatID, "
        "ThreatName, Resources, ActionSuccess, InitialDetectionTime "
        "| ConvertTo-Json -Compress",
        timeout=20,
    )
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]

    detections = []
    for d in data:
        resources = d.get("Resources") or []
        if isinstance(resources, str):
            resource = resources
        elif isinstance(resources, list) and resources:
            resource = resources[0]
        else:
            resource = ""
        # Defender prefixes file resources with "file:_"
        if isinstance(resource, str) and resource.startswith("file:_"):
            resource = resource[6:]
        detections.append({
            "id": str(d.get("DetectionID", "")),
            "threat_id": d.get("ThreatID"),
            "name": d.get("ThreatName") or "Unknown",
            "resource": resource,
            "time": d.get("InitialDetectionTime"),
        })
    return detections


def _detection_ids() -> set[str]:
    return {d["id"] for d in _list_detections() if d.get("id")}


def list_quarantined() -> list[str]:
    """Return resource paths of Defender's current quarantine entries."""
    return [d["resource"] for d in _list_detections() if d.get("resource")]


def restore_quarantined(quarantine_path: str, dest: str) -> tuple[bool, str]:
    """Restore a Defender-quarantined file to its original location.

    Defender's MpCmdRun -Restore does not accept a destination — it always
    restores to the original path. *dest* is accepted for interface parity.
    """
    match = next(
        (d for d in _list_detections() if d.get("resource") == quarantine_path),
        None,
    )
    if not match:
        return False, "No matching quarantine entry found."

    threat = (match.get("name") or "").replace("'", "''")
    rc, out, err = _ps(
        f"& \"$env:ProgramFiles\\Windows Defender\\MpCmdRun.exe\" "
        f"-Restore -Name '{threat}'",
        timeout=60,
    )
    if rc == 0:
        return True, f"Restored {match.get('resource')}."
    return False, err or out or "Restore failed."


def delete_quarantined(quarantine_path: str) -> tuple[bool, str]:
    """Permanently delete a Defender quarantine entry."""
    match = next(
        (d for d in _list_detections() if d.get("resource") == quarantine_path),
        None,
    )
    if not match:
        return False, "No matching quarantine entry found."

    threat_id = match.get("threat_id")
    if threat_id is None:
        return False, "Quarantine entry has no threat ID."
    rc, out, err = _ps(
        f"Remove-MpThreat -ThreatID {int(threat_id)}",
        timeout=30,
    )
    if rc == 0:
        return True, "Deleted."
    return False, err or out or "Delete failed."


def quarantine_file(filepath: str) -> tuple[bool, str]:
    """Move a file into the local quarantine directory.

    Defender quarantines automatically on detection; this preserves the
    AV plugin's "Quarantine" UI action for manually flagged files.
    """
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
        return True, dest
    except Exception as exc:
        return False, str(exc)


# ── macOS-specific UI hooks (no-op on Windows) ────────────


def open_login_items_settings():
    logger.info("Defender: managed by Windows; no Login Items equivalent.")


def open_fda_settings():
    logger.info("Defender: full disk access is granted by Windows automatically.")


# ── Platform interface stubs (kept for clamav_common dispatch) ──


def system_db_dir() -> str | None:
    return None


def system_db_dir_writable() -> str | None:
    return None


def system_clamd_socket_path() -> str:
    return ""


def system_clamd_conf_path() -> str:
    return ""


def find_binary(name: str) -> str | None:
    return None


def find_certs_dir() -> str | None:
    return None


def clamav_env() -> dict[str, str]:
    return {**os.environ}


def is_app_bundle() -> bool:
    return False


def daemons_approved() -> bool:
    return True


def has_full_disk_access() -> bool:
    return True


def is_clamonacc_running() -> bool:
    return is_clamd_running()
