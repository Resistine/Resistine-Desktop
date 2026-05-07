"""
Wazuh Agent Functions for Windows
Handles download, install, start/stop of the Wazuh SIEM agent and Sysmon
using PowerShell privilege escalation.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import base64
import os
import platform
import re
import socket
import subprocess
import tempfile
import winreg
import zipfile

from utils import settings
from utils.logger import logger
from utils.windows_admin import is_admin as _is_admin  # noqa: F401
from utils.windows_admin import run_privileged as _run_privileged

from plugins.wazuh.config import (
    WAZUH_MANAGER,
    WINDOWS_WAZUH_MSI_URL,
    WINDOWS_WAZUH_DIR,
    WINDOWS_SYSMON_ZIP_URL,
    WINDOWS_SYSMON_CONFIG_URL,
)

_OSSEC_CONF = os.path.join(WINDOWS_WAZUH_DIR, "ossec.conf")
_CLIENT_KEYS = os.path.join(WINDOWS_WAZUH_DIR, "client.keys")
_KEY_BACKUP = os.path.join(os.environ.get("APPDATA", ""), "Resistine", "wazuh_client.keys")
_AGENT_AUTH = os.path.join(WINDOWS_WAZUH_DIR, "agent-auth.exe")
_SERVICE_NAME = "WazuhSvc"

_RESISTINE_API_BASE = "https://validate.resistine.work"

# Sysmon paths
_SYSMON_DIR = os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Resistine", "Sysmon")
_SYSMON_EXE = os.path.join(_SYSMON_DIR, "Sysmon64.exe")
_SYSMON_CONFIG = os.path.join(_SYSMON_DIR, "sysmonconfig-export.xml")

# Sysmon localfile block to inject into ossec.conf
_SYSMON_LOCALFILE_BLOCK = """
  <localfile>
    <location>Microsoft-Windows-Sysmon/Operational</location>
    <log_format>eventchannel</log_format>
  </localfile>"""

# Windows Defender localfile block to inject into ossec.conf
_DEFENDER_LOCALFILE_BLOCK = """
  <localfile>
    <location>Microsoft-Windows-Windows Defender/Operational</location>
    <log_format>eventchannel</log_format>
  </localfile>"""




def _get_machine_guid():
    """Return the Windows MachineGuid from the registry."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return guid
    except Exception as e:
        logger.warning(f"Could not read MachineGuid: {e}")
        return None


def get_agent_name():
    """Return a stable, unique agent name: hostname + last 12 chars of MachineGuid."""
    hostname = socket.gethostname()
    guid = _get_machine_guid()
    if guid:
        suffix = guid.replace("-", "")[-12:].upper()
        name = f"{hostname}-{suffix}"
    else:
        name = hostname
    sanitized = re.sub(r"[^A-Za-z0-9.\-_]", "", name)
    if sanitized:
        return sanitized
    # Hostname was entirely non-ASCII or special chars. Fall back to a name
    # derived from the GUID so Wazuh enrollment still gets a unique value.
    if guid:
        return f"agent-{guid.replace('-', '')[-12:].upper()}"
    return "resistine-agent"


def get_agent_group():
    """Return the user's email (sanitized) as the agent group.

    Email flows into PowerShell commands (msiexec args) so it must be stripped
    of shell metacharacters using the same allowlist as get_agent_name.
    """
    email = settings.get("auth", "email", "default")
    if email and email != "default":
        sanitized = re.sub(r"[^A-Za-z0-9.\-_]", "", email.replace("@", "."))
        if sanitized:
            return sanitized
    return "default"


def needs_reenrollment():
    """Return True if the agent was enrolled under a different email."""
    enrolled = settings.get("wazuh", "enrolled_email", "")
    current = settings.get("auth", "email", "")
    if enrolled and current and enrolled != current:
        logger.info(f"[WAZUH] Enrollment mismatch: enrolled={enrolled!r} current={current!r}")
        return True
    return False


def create_wazuh_group(group_name):
    """Create a Wazuh agent group via the Resistine backend API."""
    import requests

    url = f"{_RESISTINE_API_BASE}/create-groups"
    try:
        logger.info(f"[WAZUH] create_wazuh_group -> POST {url} | name={group_name}")
        response = requests.post(url, params={"name": group_name}, timeout=30)
        logger.info(f"[WAZUH] create_wazuh_group <- HTTP {response.status_code} | body={response.text!r}")

        if response.status_code == 200:
            return True

        body = response.text.lower()
        if "already" in body or "exist" in body or response.status_code == 409:
            logger.info(f"[WAZUH] Group '{group_name}' already exists, continuing")
            return True

        logger.warning(f"[WAZUH] Unexpected response creating group: {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"[WAZUH] Failed to create group '{group_name}': {e}")
        return False


def is_agent_installed():
    """Check whether the Wazuh agent is installed on Windows."""
    return os.path.isdir(WINDOWS_WAZUH_DIR) and os.path.exists(
        os.path.join(WINDOWS_WAZUH_DIR, "wazuh-agent.exe")
    )


def get_agent_status():
    """Return 'Running', 'Stopped', or 'Not Installed'."""
    if not is_agent_installed():
        return "Not Installed"

    try:
        result = subprocess.run(
            ["sc", "query", _SERVICE_NAME],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if "RUNNING" in result.stdout:
            return "Running"
        if "STOPPED" in result.stdout:
            return "Stopped"
    except Exception as e:
        logger.warning(f"Could not query {_SERVICE_NAME} service: {e}")

    return "Stopped"


def get_package_url():
    """Return the Wazuh MSI download URL."""
    return WINDOWS_WAZUH_MSI_URL


def _is_sysmon_installed():
    """Check if Sysmon service is installed."""
    try:
        result = subprocess.run(
            ["sc", "query", "Sysmon64"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            return True
        # Try 32-bit service name
        result = subprocess.run(
            ["sc", "query", "Sysmon"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


def _download_file(url, dest_path, progress_callback=None, label="Downloading..."):
    """Download a file using PowerShell Invoke-WebRequest."""
    if progress_callback:
        progress_callback(label)

    logger.info(f"Downloading {url} -> {dest_path}")
    try:
        ps_cmd = (
            f"[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
            f"Invoke-WebRequest -Uri '{url}' -OutFile '{dest_path}' -UseBasicParsing"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and os.path.exists(dest_path):
            logger.info(f"Downloaded to {dest_path}")
            return True
        logger.error(f"Download failed: {result.stderr}")
        return False
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False


def _install_sysmon(progress_callback=None):
    """Download and install Sysmon with SwiftOnSecurity config.

    Returns True if Sysmon is already installed or was successfully installed.
    """
    if _is_sysmon_installed():
        logger.info("Sysmon already installed, skipping")
        if progress_callback:
            progress_callback("Sysmon already installed")
        return True

    if progress_callback:
        progress_callback("Setting up Sysmon...")

    # Download and extract to a temp directory first (no admin needed)
    tmp_sysmon = os.path.join(tempfile.gettempdir(), "resistine_sysmon")
    os.makedirs(tmp_sysmon, exist_ok=True)

    # Download Sysmon zip
    sysmon_zip = os.path.join(tmp_sysmon, "Sysmon.zip")
    if not _download_file(WINDOWS_SYSMON_ZIP_URL, sysmon_zip, progress_callback, "Downloading Sysmon..."):
        return False

    # Extract
    try:
        with zipfile.ZipFile(sysmon_zip, "r") as zf:
            zf.extractall(tmp_sysmon)
        logger.info(f"Extracted Sysmon to {tmp_sysmon}")
    except Exception as e:
        logger.error(f"Failed to extract Sysmon: {e}")
        return False

    # Determine correct Sysmon executable (64-bit or 32-bit)
    tmp_sysmon_exe = os.path.join(tmp_sysmon, "Sysmon64.exe")
    if not os.path.exists(tmp_sysmon_exe):
        tmp_sysmon_exe = os.path.join(tmp_sysmon, "Sysmon.exe")
        if not os.path.exists(tmp_sysmon_exe):
            logger.error("Sysmon executable not found after extraction")
            return False

    # Download SwiftOnSecurity config
    tmp_sysmon_config = os.path.join(tmp_sysmon, "sysmonconfig-export.xml")
    if not _download_file(WINDOWS_SYSMON_CONFIG_URL, tmp_sysmon_config, progress_callback, "Downloading Sysmon config..."):
        return False

    # Install Sysmon with config (requires admin) and copy files to Program Files
    if progress_callback:
        progress_callback("Installing Sysmon service...")

    install_cmd = (
        f"New-Item -ItemType Directory -Path '{_SYSMON_DIR}' -Force | Out-Null; "
        f"Copy-Item -Path '{tmp_sysmon}\\*' -Destination '{_SYSMON_DIR}' -Recurse -Force; "
        f"& '{tmp_sysmon_exe}' -accepteula -i '{tmp_sysmon_config}'"
    )
    success, output = _run_privileged(install_cmd)

    if not success and not _is_sysmon_installed():
        logger.error(f"Failed to install Sysmon: {output}")
        return False

    logger.info("Sysmon installed successfully")
    return True


def _inject_ossec_localfiles(blocks):
    """Inject one or more <localfile> blocks into ossec.conf under elevation.

    The Wazuh agent restricts ACLs on ossec.conf so a non-admin process can't
    even read it. This helper does the entire read/check/modify/write inside
    a single elevated PowerShell call, producing exactly one UAC prompt for
    the whole batch. Already-present blocks (matched by `marker`) are skipped.

    blocks: list of (marker, xml_block) tuples. `marker` is a substring whose
        presence in ossec.conf means the block is already installed.
    """
    if not blocks:
        return True

    if not os.path.exists(_OSSEC_CONF):
        logger.warning("ossec.conf not found, cannot inject localfile blocks")
        return False

    # Markers and blocks go through Base64 to dodge any quoting headaches
    # when embedded in the elevated PowerShell script.
    entries_ps = []
    for marker, block in blocks:
        m_b64 = base64.b64encode(marker.encode("utf-8")).decode("ascii")
        b_b64 = base64.b64encode(block.encode("utf-8")).decode("ascii")
        entries_ps.append(
            "    @{ "
            f"Marker = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{m_b64}')); "
            f"Block  = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b_b64}')) "
            "}"
        )
    entries_ps_str = ",`n".join(entries_ps)

    script = (
        f"$conf = '{_OSSEC_CONF}'\n"
        "if (-not (Test-Path $conf)) { throw 'ossec.conf missing' }\n"
        "$utf8NoBom = New-Object System.Text.UTF8Encoding($false)\n"
        "$content = [System.IO.File]::ReadAllText($conf, $utf8NoBom)\n"
        "if (-not $content.Contains('</ossec_config>')) { throw 'closing tag not found in ossec.conf' }\n"
        "$entries = @(\n"
        f"{entries_ps_str}\n"
        ")\n"
        "$changed = $false\n"
        "foreach ($e in $entries) {\n"
        "    if (-not $content.Contains($e.Marker)) {\n"
        "        $content = $content.Replace('</ossec_config>', $e.Block + \"`n</ossec_config>\")\n"
        "        $changed = $true\n"
        "    }\n"
        "}\n"
        "if ($changed) {\n"
        "    [System.IO.File]::WriteAllText($conf, $content, $utf8NoBom)\n"
        f"    $svc = Get-Service -Name '{_SERVICE_NAME}' -ErrorAction SilentlyContinue\n"
        "    if ($svc -and $svc.Status -eq 'Running') {\n"
        f"        Restart-Service -Name '{_SERVICE_NAME}' -Force\n"
        "    }\n"
        "}\n"
    )

    success, output = _run_privileged(script)
    if success:
        logger.info("Injected ossec.conf localfile blocks under elevation")
    else:
        logger.error(f"Failed to inject ossec.conf localfile blocks: {output}")
    return success


def _inject_sysmon_config():
    """Add Sysmon eventchannel monitoring to ossec.conf (UAC prompt)."""
    return _inject_ossec_localfiles([
        ("Microsoft-Windows-Sysmon/Operational", _SYSMON_LOCALFILE_BLOCK),
    ])


def inject_defender_config():
    """Add Windows Defender eventchannel monitoring to ossec.conf (UAC prompt)."""
    return _inject_ossec_localfiles([
        ("Microsoft-Windows-Windows Defender/Operational", _DEFENDER_LOCALFILE_BLOCK),
    ])


def download_package(progress_callback=None):
    """Download the Wazuh MSI to a temporary directory.

    Returns the local path on success, or None on failure.
    """
    url = get_package_url()
    tmp_dir = tempfile.mkdtemp(prefix="wazuh_")
    msi_path = os.path.join(tmp_dir, "wazuh-agent.msi")

    if _download_file(url, msi_path, progress_callback, "Downloading Wazuh agent..."):
        return msi_path
    return None


def start_agent():
    """Start the Wazuh agent Windows service."""
    if get_agent_status() == "Running":
        return True

    # Restore key if missing
    if os.path.exists(_KEY_BACKUP) and not os.path.exists(_CLIENT_KEYS):
        restore_cmd = (
            f"Copy-Item -Path '{_KEY_BACKUP}' -Destination '{_CLIENT_KEYS}' -Force"
        )
        _run_privileged(restore_cmd)

    success, output = _run_privileged(f"NET START {_SERVICE_NAME}")
    if success:
        logger.info("Wazuh agent started")
    else:
        logger.error(f"Failed to start agent: {output}")
    return success


def stop_agent():
    """Stop the Wazuh agent Windows service."""
    if not is_agent_installed():
        return True

    success, output = _run_privileged(f"NET STOP {_SERVICE_NAME}")

    # Verify stopped
    if get_agent_status() == "Running":
        logger.warning("Service still running after NET STOP, force-stopping")
        _run_privileged(f"Stop-Service -Name '{_SERVICE_NAME}' -Force")

    stopped = get_agent_status() != "Running"
    if stopped:
        logger.info("Wazuh agent stopped")
    else:
        logger.error("Failed to stop Wazuh agent")
    return stopped


def restore_client_key_if_needed():
    """Restore client.keys from backup if missing, then restart the agent."""
    if needs_reenrollment():
        logger.info("[WAZUH] Skipping key restore — enrolled under different email")
        return False

    if not os.path.exists(_KEY_BACKUP):
        logger.info("No client.keys backup found")
        return True

    # Only restore if missing
    script = (
        f"if (-not (Test-Path '{_CLIENT_KEYS}')) {{ "
        f"  Copy-Item -Path '{_KEY_BACKUP}' -Destination '{_CLIENT_KEYS}' -Force; "
        f"  Restart-Service -Name '{_SERVICE_NAME}'; "
        f"  Write-Output 'KEY_RESTORED' "
        f"}} else {{ "
        f"  Write-Output 'KEY_OK' "
        f"}}"
    )
    success, output = _run_privileged(script)
    if success:
        if "KEY_RESTORED" in output:
            logger.info("Restored client.keys from backup and restarted agent")
        else:
            logger.info("client.keys already present")
    return success


def remove_agent():
    """Stop and uninstall the Wazuh agent."""
    if not is_agent_installed():
        return True

    backup_dir = os.path.dirname(_KEY_BACKUP)
    script = (
        f"NET STOP {_SERVICE_NAME} 2>$null; "
        f"New-Item -ItemType Directory -Path '{backup_dir}' -Force | Out-Null; "
        f"if (Test-Path '{_CLIENT_KEYS}') {{ Copy-Item '{_CLIENT_KEYS}' '{_KEY_BACKUP}' -Force }}; "
        # Uninstall via MSI product code lookup
        f"$app = Get-WmiObject -Class Win32_Product | Where-Object {{ $_.Name -like '*Wazuh*' }}; "
        f"if ($app) {{ $app.Uninstall() }}; "
        # Fallback: remove directory
        f"if (Test-Path '{WINDOWS_WAZUH_DIR}') {{ Remove-Item -Recurse -Force '{WINDOWS_WAZUH_DIR}' }}"
    )
    success, output = _run_privileged(script, timeout=300)
    if success:
        logger.info("Wazuh agent removed successfully")
    else:
        logger.error(f"Failed to remove agent: {output}")
    return success


def full_install(progress_callback=None):
    """Orchestrate the complete install flow:
    1. Download & install Sysmon with SwiftOnSecurity config
    2. Download Wazuh MSI
    3. Install Wazuh agent
    4. Configure ossec.conf (agent name, Sysmon monitoring)
    5. Enroll or restore keys
    6. Start the service
    """
    # Phase 1: Install Sysmon
    if progress_callback:
        progress_callback("Setting up Sysmon...")
    if not _install_sysmon(progress_callback):
        logger.warning("Sysmon installation failed, continuing with Wazuh install")
        # Non-fatal: Wazuh can still work without Sysmon

    # Phase 2: Download Wazuh MSI
    if progress_callback:
        progress_callback("Downloading Wazuh agent...")
    msi_path = download_package(progress_callback)
    if not msi_path:
        if progress_callback:
            progress_callback("Download failed")
        return False

    # Phase 3: Create agent group
    agent_name = get_agent_name()
    agent_group = get_agent_group()

    if progress_callback:
        progress_callback(f"Creating agent group '{agent_group}'...")
    if not create_wazuh_group(agent_group):
        logger.warning(f"[WAZUH] Could not create group '{agent_group}', falling back to 'default'")
        agent_group = "default"

    # Phase 4: Install Wazuh via MSI (silent install with params)
    if progress_callback:
        progress_callback("Installing Wazuh agent (admin privileges required)...")

    install_cmd = (
        f"msiexec.exe /i '{msi_path}' /qn "
        f"WAZUH_MANAGER='{WAZUH_MANAGER}' "
        f"WAZUH_AGENT_NAME='{agent_name}' "
        f"WAZUH_AGENT_GROUP='{agent_group}'"
    )
    success, output = _run_privileged(install_cmd, timeout=300)

    if not success and not is_agent_installed():
        logger.error(f"MSI install failed: {output}")
        if progress_callback:
            progress_callback("Installation failed")
        return False

    # Phase 5: Patch agent name in ossec.conf
    if progress_callback:
        progress_callback("Configuring agent...")

    patch_cmd = (
        f"(Get-Content '{_OSSEC_CONF}') "
        f"-replace '<agent_name>.*</agent_name>', '<agent_name>{agent_name}</agent_name>' | "
        f"Set-Content '{_OSSEC_CONF}'"
    )
    _run_privileged(patch_cmd)

    # Phase 6: Inject Sysmon and Defender monitoring into ossec.conf
    # Single UAC prompt for both blocks.
    _inject_ossec_localfiles([
        ("Microsoft-Windows-Sysmon/Operational", _SYSMON_LOCALFILE_BLOCK),
        ("Microsoft-Windows-Windows Defender/Operational", _DEFENDER_LOCALFILE_BLOCK),
    ])

    # Phase 7: Enrollment — restore existing key or enroll fresh
    backup_dir = os.path.dirname(_KEY_BACKUP)
    can_restore = (not needs_reenrollment()) and os.path.exists(_KEY_BACKUP)

    if can_restore:
        if progress_callback:
            progress_callback("Restoring previous enrollment...")
        restore_cmd = (
            f"Copy-Item -Path '{_KEY_BACKUP}' -Destination '{_CLIENT_KEYS}' -Force"
        )
        success_restore, _ = _run_privileged(restore_cmd)
        if success_restore:
            logger.info("[WAZUH] Restored existing enrollment key")
        else:
            logger.warning("[WAZUH] Key restore failed, will enroll fresh")
            can_restore = False

    if not can_restore:
        if progress_callback:
            progress_callback("Enrolling agent with manager...")
        enroll_cmd = (
            f"& '{_AGENT_AUTH}' -m '{WAZUH_MANAGER}' -A '{agent_name}' -G '{agent_group}'"
        )
        enroll_success, enroll_output = _run_privileged(enroll_cmd)

        if enroll_success:
            logger.info("[WAZUH] Fresh enrollment succeeded")
        else:
            logger.warning(f"[WAZUH] agent-auth enrollment failed: {enroll_output}")

        # Backup the new key
        backup_cmd = (
            f"New-Item -ItemType Directory -Path '{backup_dir}' -Force | Out-Null; "
            f"if (Test-Path '{_CLIENT_KEYS}') {{ Copy-Item '{_CLIENT_KEYS}' '{_KEY_BACKUP}' -Force }}"
        )
        _run_privileged(backup_cmd)

    # Phase 8: Start the service
    if progress_callback:
        progress_callback("Starting Wazuh agent...")

    start_cmd = f"NET START {_SERVICE_NAME}"
    _run_privileged(start_cmd)

    # Verify
    if get_agent_status() == "Running":
        logger.info("Wazuh agent installed and running")
        if progress_callback:
            progress_callback("Wazuh agent installed and running")
    else:
        logger.warning("Agent installed but not yet running")
        if progress_callback:
            progress_callback("Wazuh agent installed (may need manual start)")

    # Record enrollment email
    settings.set("wazuh", "enrolled_email", settings.get("auth", "email", ""))

    logger.info("Wazuh full install completed successfully")
    return True
