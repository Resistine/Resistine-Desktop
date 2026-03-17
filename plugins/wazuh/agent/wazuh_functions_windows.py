"""
Wazuh Agent Functions for Windows
Handles download, install, start/stop of the Wazuh SIEM agent.
Uses the Resistine enrollment API for agent registration.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import re
import socket
import subprocess
import tempfile

import requests

from utils import settings
from utils.logger import logger
from plugins.wazuh.config import (
    WAZUH_MANAGER,
    WAZUH_VERSION,
    WAZUH_BASE_URL,
)

_INSTALL_DIR = r"C:\Program Files (x86)\ossec-agent"
_AGENT_EXE = os.path.join(_INSTALL_DIR, "wazuh-agent.exe")
_CLIENT_KEYS = os.path.join(_INSTALL_DIR, "client.keys")
_OSSEC_CONF = os.path.join(_INSTALL_DIR, "ossec.conf")
_KEY_BACKUP = os.path.join(
    os.environ.get("ProgramData", r"C:\ProgramData"),
    "Resistine", "wazuh_client.keys"
)

_RESISTINE_API_BASE = "https://validate.resistine.work"
_MSI_FILENAME = f"wazuh-agent-{WAZUH_VERSION}-1.msi"
_MSI_URL = f"{WAZUH_BASE_URL}/{_MSI_FILENAME}"


# --------------------------------------------------
# Identity helpers
# --------------------------------------------------


def _get_hardware_uuid() -> str | None:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"],
            capture_output=True, text=True, timeout=10,
        )
        uuid = result.stdout.strip()
        if uuid:
            return uuid
    except Exception as e:
        logger.warning(f"Could not read hardware UUID: {e}")
    return None


def get_agent_name() -> str:
    """Return a stable, org-unique agent name: hostname + last 12 chars of hardware UUID."""
    hostname = socket.gethostname()
    uuid = _get_hardware_uuid()
    if uuid:
        suffix = uuid.replace("-", "")[-12:].upper()
        name = f"{hostname}-{suffix}"
    else:
        name = hostname
    # Wazuh allows: alphanumerics, hyphens, underscores, dots
    return re.sub(r"[^A-Za-z0-9.\-_]", "", name)


def get_agent_group() -> str:
    """Return the user's email (sanitized) as the agent group.

    Replaces '@' with '.' so the group name is a valid Wazuh identifier.
    Falls back to 'default' if no email is stored.
    """
    email = settings.get("auth", "email", "default")
    if email and email != "default":
        return email.replace("@", ".")
    return "default"


def needs_reenrollment() -> bool:
    """Return True if the agent was enrolled under a different email than the current user."""
    enrolled = settings.get("wazuh", "enrolled_email", "")
    current = settings.get("auth", "email", "")
    if enrolled and current and enrolled != current:
        logger.info(f"[WAZUH] Enrollment mismatch: enrolled={enrolled!r} current={current!r}")
        return True
    return False


# --------------------------------------------------
# Install state
# --------------------------------------------------

def is_agent_installed() -> bool:
    return os.path.isfile(_AGENT_EXE)


def get_agent_status() -> str:
    """Return 'Running', 'Stopped', or 'Not Installed'."""
    if not is_agent_installed():
        return "Not Installed"
    try:
        result = subprocess.run(
            ["sc", "query", "WazuhSvc"],
            capture_output=True, text=True, timeout=10,
        )
        if "RUNNING" in result.stdout:
            return "Running"
    except Exception as e:
        logger.warning(f"Could not query WazuhSvc: {e}")
    return "Stopped"


# --------------------------------------------------
# Group creation via Resistine API
# --------------------------------------------------

def create_wazuh_group(group_name: str) -> bool:
    """Create a Wazuh agent group via the Resistine backend API."""
    url = f"{_RESISTINE_API_BASE}/create-groups"
    try:
        logger.info(f"[WAZUH] create_wazuh_group -> POST {url} | name={group_name}")
        response = requests.post(url, params={"name": group_name}, timeout=30)
        logger.info(f"[WAZUH] create_wazuh_group <- HTTP {response.status_code} | body={response.text!r}")

        if response.status_code == 200:
            logger.info(f"[WAZUH] Group '{group_name}' created successfully")
            return True

        body = response.text.lower()
        if "already" in body or "exist" in body or response.status_code == 409:
            logger.info(f"[WAZUH] Group '{group_name}' already exists, continuing")
            return True

        logger.warning(f"[WAZUH] Unexpected response creating group: {response.status_code} {response.text!r}")
        return False
    except Exception as e:
        logger.error(f"[WAZUH] Failed to create group '{group_name}': {e}")
        return False


# --------------------------------------------------
# Enrollment via Resistine API (replaces agent-auth)
# --------------------------------------------------

def _request_enrollment_otp(email: str) -> bool:
    """Phase 1 — request OTP for the given email."""
    url = f"{_RESISTINE_API_BASE}/wazuh-agent/request"
    try:
        r = requests.post(url, json={"email": email}, timeout=30)
        if r.status_code == 200:
            logger.info("[WAZUH] OTP sent successfully")
            return True
        logger.warning(f"[WAZUH] OTP request failed: {r.status_code} {r.text!r}")
        return False
    except Exception as e:
        logger.error(f"[WAZUH] OTP request error: {e}")
        return False


def _enroll_device(email: str, otp: str, device_name: str) -> dict | None:
    """Phase 2 — submit OTP and enroll device. Returns enrollment data or None."""
    url = f"{_RESISTINE_API_BASE}/wazuh-agent/enroll"
    try:
        r = requests.post(url, json={
            "email": email,
            "otp": otp,
            "device_name": device_name,
            "device_type": "windows",
        }, timeout=30)
        if r.status_code == 200:
            logger.info("[WAZUH] Device enrolled successfully")
            return r.json()
        logger.warning(f"[WAZUH] Enrollment failed: {r.status_code} {r.text!r}")
        return None
    except Exception as e:
        logger.error(f"[WAZUH] Enrollment request error: {e}")
        return None


# --------------------------------------------------
# Key backup / restore
# --------------------------------------------------

def _backup_client_key() -> None:
    backup_dir = os.path.dirname(_KEY_BACKUP)
    os.makedirs(backup_dir, exist_ok=True)
    try:
        if os.path.isfile(_CLIENT_KEYS):
            import shutil
            shutil.copy2(_CLIENT_KEYS, _KEY_BACKUP)
            logger.info(f"[WAZUH] Backed up client.keys to {_KEY_BACKUP}")
    except Exception as e:
        logger.warning(f"[WAZUH] Could not back up client.keys: {e}")


def _restore_client_key() -> bool:
    """Copy key backup into the install dir. Returns True if restored."""
    if not os.path.isfile(_KEY_BACKUP):
        return False
    try:
        import shutil
        shutil.copy2(_KEY_BACKUP, _CLIENT_KEYS)
        logger.info("[WAZUH] Restored client.keys from backup")
        return True
    except Exception as e:
        logger.warning(f"[WAZUH] Could not restore client.keys: {e}")
        return False


def restore_client_key_if_needed() -> bool:
    """Restore client.keys from backup if missing, then restart the agent."""
    if needs_reenrollment():
        logger.info("[WAZUH] Skipping key restore — enrolled under different email")
        return False
    if not os.path.isfile(_KEY_BACKUP):
        return True
    if os.path.isfile(_CLIENT_KEYS) and os.path.getsize(_CLIENT_KEYS) > 0:
        return True
    if _restore_client_key():
        return start_agent()
    return False


# --------------------------------------------------
# Start / Stop
# --------------------------------------------------

def _run_elevated(command: str) -> bool:
    """Run a command elevated via PowerShell Start-Process."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Start-Process cmd -ArgumentList '/c {command}' "
                "-Verb RunAs -Wait -WindowStyle Hidden",
            ],
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"[WAZUH] Elevated command failed: {e}")
        return False


def start_agent() -> bool:
    success = _run_elevated("net start WazuhSvc")
    if success:
        logger.info("[WAZUH] Agent started")
    else:
        logger.error("[WAZUH] Failed to start agent")
    return success


def stop_agent() -> bool:
    success = _run_elevated("net stop WazuhSvc")
    if success:
        logger.info("[WAZUH] Agent stopped")
    else:
        logger.error("[WAZUH] Failed to stop agent")
    return success
# --------------------------------------------------
# Full install
# --------------------------------------------------

def full_install(progress_callback=None, otp_provider=None) -> bool:
    """Orchestrate the complete install flow for Windows.

    otp_provider: callable() -> str that returns the 6-digit OTP entered
    by the user (e.g. a dialog prompt in the UI). If None, enrollment
    is skipped and the agent relies on auto-enrollment via the manager.
    """
    email = settings.get("auth", "email", "")
    agent_name = get_agent_name()
    agent_group = get_agent_group()

    # 1. Download MSI
    if progress_callback:
        progress_callback("Downloading Wazuh agent...")
    pkg_path = _download_msi(progress_callback)
    if not pkg_path:
        return False

    # 2. Create group via API
    if progress_callback:
        progress_callback(f"Creating agent group '{agent_group}'...")
    if not create_wazuh_group(agent_group):
        logger.warning(f"[WAZUH] Could not create group '{agent_group}', falling back to 'default'")
        agent_group = "default"

    # 3. Install MSI silently
    if progress_callback:
        progress_callback("Installing Wazuh agent...")
    if not _install_msi(pkg_path, agent_name, agent_group, progress_callback):
        return False

    # 4. Enrollment — restore backup key or use API enrollment
    can_restore = (not needs_reenrollment()) and os.path.isfile(_KEY_BACKUP)

    if can_restore:
        if progress_callback:
            progress_callback("Restoring previous enrollment key...")
        if _restore_client_key():
            logger.info("[WAZUH] Existing enrollment key restored")
        else:
            logger.warning("[WAZUH] Key restore failed, falling back to API enrollment")
            can_restore = False

    if not can_restore and email and otp_provider:
        if progress_callback:
            progress_callback("Requesting enrollment code...")
        if _request_enrollment_otp(email):
            otp = otp_provider()  # UI prompts the user to enter the OTP
            if otp:
                if progress_callback:
                    progress_callback("Enrolling device...")
                enrollment = _enroll_device(email, otp, agent_name)
                if enrollment:
                    _write_client_key(enrollment.get("agent_id"), enrollment.get("installer"))
                    _backup_client_key()
                    logger.info("[WAZUH] API enrollment complete")
                else:
                    logger.warning("[WAZUH] API enrollment failed — agent will use auto-enrollment")
            else:
                logger.warning("[WAZUH] No OTP provided — agent will use auto-enrollment")
        else:
            logger.warning("[WAZUH] OTP request failed — agent will use auto-enrollment")

    # 5. Start the agent
    if progress_callback:
        progress_callback("Starting Wazuh agent...")
    start_agent()

    if get_agent_status() == "Running":
        if progress_callback:
            progress_callback("Wazuh agent installed and running")
        logger.info("[WAZUH] Agent installed and running")
    else:
        logger.warning("[WAZUH] Agent installed but not yet running")
        if progress_callback:
            progress_callback("Wazuh agent installed (may need manual start)")

    settings.set("wazuh", "enrolled_email", email)
    return True


# --------------------------------------------------
# Internal helpers
# --------------------------------------------------

def _download_msi(progress_callback=None) -> str | None:
    tmp_dir = tempfile.mkdtemp(prefix="wazuh_")
    msi_path = os.path.join(tmp_dir, _MSI_FILENAME)
    try:
        logger.info(f"[WAZUH] Downloading MSI from {_MSI_URL}")
        with requests.get(_MSI_URL, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(msi_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logger.info(f"[WAZUH] Downloaded MSI to {msi_path}")
        return msi_path
    except Exception as e:
        logger.error(f"[WAZUH] MSI download failed: {e}")
        if progress_callback:
            progress_callback("Download failed")
        return None


def _install_msi(msi_path: str, agent_name: str, agent_group: str, progress_callback=None) -> bool:
    cmd = [
        "msiexec.exe", "/i", msi_path, "/qn",
        f"WAZUH_MANAGER={WAZUH_MANAGER}",
        f"WAZUH_AGENT_NAME={agent_name}",
        f"WAZUH_AGENT_GROUP={agent_group}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            logger.info("[WAZUH] MSI installed successfully")
            return True
        logger.error(f"[WAZUH] MSI install failed: rc={result.returncode} {result.stderr}")
        if progress_callback:
            progress_callback("Installation failed")
        return False
    except Exception as e:
        logger.error(f"[WAZUH] MSI install error: {e}")
        if progress_callback:
            progress_callback(f"Installation error: {e}")
        return False


def _write_client_key(agent_id: str | None, installer: str | None) -> None:
    """Extract and write client.keys from the installer script returned by the API."""
    if not agent_id or not installer:
        return
    try:
        # The installer script contains $AgentKey = "<key>" — extract it
        match = re.search(r'\$AgentKey\s*=\s*"([^"]+)"', installer or "")
        if match:
            key_line = f"{agent_id} {get_agent_name()} any {match.group(1)}\n"
            os.makedirs(os.path.dirname(_CLIENT_KEYS), exist_ok=True)
            with open(_CLIENT_KEYS, "w") as f:
                f.write(key_line)
            logger.info("[WAZUH] Wrote client.keys from API enrollment response")
    except Exception as e:
        logger.warning(f"[WAZUH] Could not write client.keys: {e}")