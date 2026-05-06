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
from utils.windows_admin import run_privileged

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

# ── Status cache ──────────────────────────────────────────
_status_cache: dict = {}
_status_cache_time: float = 0.0
_status_cache_lock = threading.Lock()
_STATUS_TTL: float = 8.0  # seconds; fits within the 10 s UI poll cycle


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
    """Return a parsed Get-MpComputerStatus snapshot, or {} on failure.

    Results are cached for *_STATUS_TTL* seconds to avoid spawning
    redundant PowerShell processes when multiple callers query status
    in the same UI poll cycle.
    """
    global _status_cache, _status_cache_time

    now = time.monotonic()
    with _status_cache_lock:
        if _status_cache and (now - _status_cache_time) < _STATUS_TTL:
            return _status_cache

    rc, out, _ = _ps(
        "Get-MpComputerStatus | Select-Object "
        "AntivirusEnabled, RealTimeProtectionEnabled, "
        "AntivirusSignatureLastUpdated, AntivirusSignatureVersion, "
        "AMServiceEnabled "
        "| ConvertTo-Json -Compress",
        timeout=15,
    )
    if rc != 0 or not out:
        result = {}
    else:
        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            result = {}

    with _status_cache_lock:
        _status_cache = result
        _status_cache_time = time.monotonic()

    return result


def _invalidate_status_cache() -> None:
    """Force the next _mp_status() call to re-query Defender."""
    global _status_cache, _status_cache_time
    with _status_cache_lock:
        _status_cache = {}
        _status_cache_time = 0.0


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
    """Check whether the antivirus engine is installed.

    Named ``is_clamav_installed`` for interface parity with the ClamAV
    backend.  On Windows this delegates to Defender's availability check.
    """
    return is_available()


def is_clamd_running() -> bool:
    """Check whether real-time protection is active.

    Named ``is_clamd_running`` for interface parity with the ClamAV
    backend (clamd daemon).  On Windows this checks Defender's
    RealTimeProtectionEnabled status.
    """
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
    """Start the antivirus daemon (no-op on Windows).

    Named ``start_clamd`` for interface parity.  Defender's real-time
    protection service is managed by Windows and cannot be started
    independently.  Use activate_system_daemons() instead.
    """
    return True, "Defender is managed by Windows."


def stop_clamd() -> tuple[bool, str]:
    """Stop the antivirus daemon (no-op on Windows).

    Named ``stop_clamd`` for interface parity.  Defender's service is
    OS-managed.  Use deactivate_system_daemons() instead.
    """
    return True, "Defender is managed by Windows."


def activate_system_daemons() -> tuple[bool, str]:
    """Enable Defender real-time protection (requires admin).

    Uses UAC elevation if the current process is not running as
    administrator.  Maps to the ClamAV interface's daemon-start action.
    """
    ok, output = run_privileged(
        "Set-MpPreference -DisableRealtimeMonitoring $false",
        timeout=15,
    )
    _invalidate_status_cache()
    if ok:
        return True, "Real-time protection enabled."
    return False, output or "Failed to enable real-time protection."


def deactivate_system_daemons() -> tuple[bool, str]:
    """Disable Defender real-time protection (requires admin).

    Uses UAC elevation if the current process is not running as
    administrator.  Maps to the ClamAV interface's daemon-stop action.
    """
    ok, output = run_privileged(
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        timeout=15,
    )
    _invalidate_status_cache()
    if ok:
        return True, "Real-time protection disabled."
    return False, output or "Failed to disable real-time protection."


def ensure_daemons_registered():
    """No-op — Defender ships with Windows."""


def refresh_system_configs():
    """No-op — no Resistine-managed system configs on Windows."""


# ── Signature updates ─────────────────────────────────────


def run_freshclam(on_line: Callable | None = None) -> tuple[bool, str]:
    """Update antivirus signature definitions.

    Named ``run_freshclam`` for interface parity with the ClamAV
    backend (freshclam tool).  On Windows this invokes Defender's
    Update-MpSignature cmdlet.
    """
    if on_line:
        on_line("Updating Windows Defender signatures...")
    rc, out, err = _ps("Update-MpSignature", timeout=300)
    if rc == 0:
        return True, "Signatures updated successfully."
    return False, err or out or f"Update-MpSignature exited with code {rc}"


# ── Scanning ──────────────────────────────────────────────

# MpCmdRun exit codes: 0 = clean, 2 = threat found
_MPCMDRUN: str | None = None


def _find_mpcmdrun() -> str | None:
    """Locate MpCmdRun.exe (cached after first lookup)."""
    global _MPCMDRUN
    if _MPCMDRUN is not None:
        return _MPCMDRUN or None
    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        path = os.path.join(base, "Windows Defender", "MpCmdRun.exe")
        if os.path.isfile(path):
            _MPCMDRUN = path
            return path
    _MPCMDRUN = ""
    return None


def _scan_single_file(filepath: str) -> str:
    """Scan one file with MpCmdRun and return a ClamAV-style result line.

    Returns  "<filepath>: <ThreatName> FOUND"  or  "<filepath>: OK".
    """
    exe = _find_mpcmdrun()
    if not exe:
        return f"{filepath}: OK"
    try:
        proc = subprocess.run(
            [exe, "-Scan", "-ScanType", "3", "-File", filepath,
             "-DisableRemediation"],
            capture_output=True, text=True, timeout=60,
            creationflags=_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return f"{filepath}: OK"
    if proc.returncode == 2:
        # Try to extract threat name from stdout
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Threat"):
                name = stripped.split(":", 1)[-1].strip() if ":" in stripped else "Malware"
                return f"{filepath}: {name} FOUND"
        return f"{filepath}: Malware FOUND"
    return f"{filepath}: OK"


def scan_path(
    target: str,
    on_line: Callable | None = None,
    cancel: "threading.Event | None" = None,
    proc_ref: "list | None" = None,
    on_total: Callable | None = None,
) -> dict:
    """Scan a file or directory with Windows Defender.

    Uses MpCmdRun.exe per-file for fast scanning with real-time progress,
    matching the ClamAV backend's per-file callback behaviour.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

    # Single file scan
    if os.path.isfile(target):
        if on_total:
            on_total(1)
        if on_line:
            on_line(f"Scanning {os.path.basename(target)}...")
        start = time.monotonic()
        line = _scan_single_file(target)
        if on_line:
            on_line(line)
        result["scanned"] = 1
        if "FOUND" in line:
            result["infected"] = 1
            result["infections"] = [line]
        result["duration"] = _format_duration(time.monotonic() - start)
        return result

    # Directory scan — walk, then scan per-file with parallel workers
    whitelist = set(get_whitelist())
    excl = get_scan_exclusions()
    excluded_ext = frozenset(excl["extensions"])
    max_bytes = excl["max_size_mb"] * 1048576 if excl["max_size_mb"] else 0
    files = list(_walk_files(target, whitelist, excluded_ext, max_bytes))

    if not files:
        if on_line:
            on_line("No files matched scan filters.")
        result["duration"] = "0.000 sec (0 s)"
        return result

    if on_total:
        on_total(len(files))
    if on_line:
        on_line(
            f"Scanning {len(files)} files in "
            f"{os.path.basename(target) or target}...",
        )

    start = time.monotonic()
    scanned = 0
    infected = 0
    infections: list[str] = []

    pool = ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS)
    try:
        futures = {
            pool.submit(_scan_single_file, f): f for f in files
        }
        for future in as_completed(futures):
            if cancel and cancel.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                result["error"] = "Scan cancelled."
                return result
            try:
                line = future.result()
            except Exception:
                continue
            scanned += 1
            if on_line:
                on_line(line)
            if "FOUND" in line:
                infected += 1
                infections.append(line)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    result["scanned"] = scanned
    result["infected"] = infected
    result["infections"] = infections
    result["duration"] = _format_duration(time.monotonic() - start)
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
    """Return file paths currently in quarantine.

    Named ``list_quarantined`` for interface parity.  On Windows this
    queries Defender's threat detection history rather than a local
    quarantine directory.
    """
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


# ── Platform interface stubs ──────────────────────────────
# The functions below exist solely for interface parity with the ClamAV
# backend on macOS/Linux.  They return safe no-op values because
# Windows Defender does not use ClamAV binaries, sockets, configs,
# bundle detection, or FDA/Login Items approval.


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
    """Check whether on-access scanning is active.

    Named ``is_clamonacc_running`` for interface parity with the ClamAV
    backend (clamonacc daemon).  On Windows, Defender's real-time
    protection serves the same role.
    """
    return is_clamd_running()
