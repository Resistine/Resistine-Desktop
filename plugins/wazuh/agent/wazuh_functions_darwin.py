"""
Wazuh Agent Functions for macOS
Handles download, install, start/stop of the Wazuh SIEM agent via osascript
privilege escalation.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import platform
import socket
import subprocess
import tempfile

from utils import settings
from utils.logger import logger

from plugins.wazuh.config import (
    WAZUH_BASE_URL,
    WAZUH_ENV_FILE,
    WAZUH_INSTALL_DIR,
    WAZUH_LAUNCHD_PLIST,
    WAZUH_MANAGER,
    WAZUH_PKG_ARCH_MAP,
    WAZUH_VERSION,
)

_WAZUH_CONTROL = f"{WAZUH_INSTALL_DIR}/bin/wazuh-control"


def _get_hardware_uuid():
    """Return the macOS hardware UUID, or None on failure.

    The hardware UUID is stable across OS reinstalls and unique per physical
    machine, making it suitable as a stable disambiguator for agent names.
    """
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                # Line format: "IOPlatformUUID" = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
                return line.split('"')[-2]
    except Exception as e:
        logger.warning(f"Could not read hardware UUID: {e}")
    return None


def get_agent_name():
    """Return a stable, org-unique agent name: hostname + last 8 chars of hardware UUID.

    Using hostname alone causes collisions when multiple machines share a
    default name (e.g. 'MacBook-Air.local').  Appending a short hardware UUID
    suffix makes the name unique per physical device while keeping it
    human-readable on the Wazuh dashboard.

    The result is restricted to alphanumerics, hyphens, and dots to prevent
    shell injection when the name is interpolated into privileged scripts.
    """
    import re
    hostname = socket.gethostname()
    uuid = _get_hardware_uuid()
    if uuid:
        suffix = uuid.replace("-", "")[-8:].upper()
        name = f"{hostname}-{suffix}"
    else:
        name = hostname
    # Strip any character that isn't safe in a shell argument or Wazuh agent
    # name.  Wazuh allows: alphanumerics, hyphens, underscores, dots.
    return re.sub(r"[^A-Za-z0-9.\-_]", "", name)


def get_agent_group():
    """Return the user's email (sanitized) as the agent group.

    Replaces '@' with '.' so the group name is a valid Wazuh identifier.
    Falls back to 'default' if no email is stored.
    """
    email = settings.get("auth", "email", "default")
    if email and email != "default":
        return email.replace("@", ".")
    return "default"


def needs_reenrollment():
    """Return True if the agent was enrolled under a different email than the current user.

    This covers: new login with different email, org change, etc.
    Returns False if no prior enrollment is recorded (safe to proceed normally).
    """
    enrolled = settings.get("wazuh", "enrolled_email", "")
    current = settings.get("auth", "email", "")
    if enrolled and current and enrolled != current:
        logger.info(f"[WAZUH] Enrollment mismatch: enrolled={enrolled!r} current={current!r}")
        return True
    return False


_RESISTINE_API_BASE = "https://validate.resistine.work"


def create_wazuh_group(group_name):
    """Create a Wazuh agent group via the Resistine backend API.

    Calls POST /create-groups?name=<group_name>.  If the group already
    exists the backend returns a non-200 response with a descriptive
    message; we treat that as success so the install can proceed normally.

    Returns True if the group is ready to use, False on unexpected error.
    """
    import requests

    url = f"{_RESISTINE_API_BASE}/create-groups"
    try:
        logger.info(f"[WAZUH] create_wazuh_group -> POST {url} | name={group_name}")
        response = requests.post(url, params={"name": group_name}, timeout=30)
        logger.info(f"[WAZUH] create_wazuh_group <- HTTP {response.status_code} | body={response.text!r}")

        if response.status_code == 200:
            logger.info(f"[WAZUH] Group '{group_name}' created successfully")
            return True

        # 422 or similar — group may already exist; treat as success
        body = response.text.lower()
        if "already" in body or "exist" in body or response.status_code == 409:
            logger.info(f"[WAZUH] Group '{group_name}' already exists, continuing")
            return True

        logger.warning(f"[WAZUH] Unexpected response creating group '{group_name}': {response.status_code} {response.text!r}")
        return False
    except Exception as e:
        logger.error(f"[WAZUH] Failed to create group '{group_name}': {e}")
        return False


def get_package_url():
    """Build the full .pkg download URL from config constants + architecture."""
    arch = platform.machine()
    arch_suffix = WAZUH_PKG_ARCH_MAP.get(arch, "arm64")
    filename = f"wazuh-agent-{WAZUH_VERSION}.{arch_suffix}.pkg"
    return f"{WAZUH_BASE_URL}/{filename}"


def is_agent_installed():
    """Check whether the Wazuh agent is installed.

    The agent's /Library/Ossec/ directory is root-owned and not readable by
    normal users, so checking for files inside it returns False even when
    they exist.  Instead we check for the directory itself (os.path.isdir
    succeeds without read permission) or the launchd plist which is
    world-readable.
    """
    return os.path.isdir(WAZUH_INSTALL_DIR) or os.path.exists(WAZUH_LAUNCHD_PLIST)


def get_agent_status():
    """Return 'Running', 'Stopped', or 'Not Installed'.

    Checks launchd first, then falls back to checking for running
    wazuh-agentd processes (covers the case where the agent was started
    via wazuh-control instead of launchd).
    """
    if not is_agent_installed():
        return "Not Installed"

    # Check launchd service first
    try:
        result = subprocess.run(
            ["launchctl", "print", "system/com.wazuh.agent"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and "state = running" in result.stdout:
            return "Running"
    except Exception as e:
        logger.warning(f"Could not query launchd for Wazuh agent: {e}")

    # Fallback: check if wazuh-agentd process is running (covers
    # agents started via wazuh-control instead of launchd)
    try:
        result = subprocess.run(
            ["pgrep", "-x", "wazuh-agentd"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "Running"
    except Exception as e:
        logger.warning(f"Could not check wazuh-agentd process: {e}")

    return "Stopped"


def _run_privileged(script, timeout=120):
    """Execute a shell script with admin privileges via osascript.

    Shows the native macOS password dialog. Returns (success, output).
    """
    try:
        escaped = script.replace("\\", "\\\\").replace('"', '\\"')
        cmd = [
            "osascript", "-e",
            f'do shell script "{escaped}" with administrator privileges',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip() or result.stderr.strip()
        logger.info(f"_run_privileged: rc={result.returncode} output={output!r}")
        return (result.returncode == 0, output)
    except subprocess.TimeoutExpired:
        logger.error("Privileged command timed out")
        return (False, "Command timed out")
    except Exception as e:
        logger.error(f"Privileged command error: {e}")
        return (False, str(e))


def download_package(progress_callback=None):
    """Download the Wazuh .pkg to a temporary directory using curl.

    Returns the local path on success, or None on failure.
    """
    url = get_package_url()
    tmp_dir = tempfile.mkdtemp(prefix="wazuh_")
    pkg_path = os.path.join(tmp_dir, "wazuh-agent.pkg")

    if progress_callback:
        progress_callback("Downloading Wazuh agent...")

    logger.info(f"Downloading Wazuh package from {url}")
    try:
        result = subprocess.run(
            ["/usr/bin/curl", "-fSL", "-o", pkg_path, url],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error(f"curl failed: {result.stderr}")
            return None
        logger.info(f"Downloaded to {pkg_path}")
        return pkg_path
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None


def write_env_file(agent_name, agent_group):
    """Write the Wazuh environment file used during package installation."""
    content = (
        f"WAZUH_MANAGER='{WAZUH_MANAGER}'\n"
        f"WAZUH_AGENT_NAME='{agent_name}'\n"
        f"WAZUH_AGENT_GROUP='{agent_group}'\n"
    )
    try:
        with open(WAZUH_ENV_FILE, "w") as f:
            f.write(content)
        logger.info(f"Wrote env file to {WAZUH_ENV_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to write env file: {e}")
        return False


def _is_service_loaded():
    """Check whether the Wazuh launchd service is already bootstrapped."""
    try:
        result = subprocess.run(
            ["launchctl", "print", "system/com.wazuh.agent"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def start_agent():
    """Start the Wazuh agent via launchd.

    Uses ``launchctl bootstrap`` to load the plist and let launchd
    manage all child processes.  This ensures that ``bootout`` can
    cleanly terminate the entire process tree later, avoiding orphans.

    We intentionally do NOT call ``wazuh-control start`` because it
    spawns processes outside launchd's supervision, which causes
    orphaned processes when ``bootout`` is used to stop the agent.

    If a client.keys backup exists but client.keys is missing (e.g.
    after the app was reinstalled), the key is restored in the same
    privileged call to avoid a second password prompt.
    """
    if _is_service_loaded():
        logger.info("Wazuh launchd service already loaded, nothing to do")
        return True

    parts = []
    # Restore client.keys from backup if it's missing — checked unprivileged
    # first (backup lives outside /Library/Ossec/ so is always readable).
    if os.path.exists(_KEY_BACKUP):
        parts.append(
            f"if [ ! -s '{_CLIENT_KEYS}' ]; then "
            # Try Keychain first (encrypted at rest), fall back to file.
            f"KC=$(security find-generic-password -k '{_KEYCHAIN}' -s '{_KC_SERVICE}' -a '{_KC_ACCOUNT}' -w 2>/dev/null); "
            f"if [ -n \"$KC\" ]; then "
            f"echo \"$KC\" > '{_CLIENT_KEYS}'; "
            f"elif [ -s '{_KEY_BACKUP}' ]; then "
            f"cp '{_KEY_BACKUP}' '{_CLIENT_KEYS}'; "
            f"fi; "
            f"if [ -s '{_CLIENT_KEYS}' ]; then "
            f"chmod 640 '{_CLIENT_KEYS}' && chown root:wazuh '{_CLIENT_KEYS}' && echo KEY_RESTORED; "
            f"fi; "
            f"fi"
        )
    parts.append(f"launchctl bootstrap system '{WAZUH_LAUNCHD_PLIST}'")

    script = "; ".join(parts)
    success, output = _run_privileged(script)
    if success:
        if "KEY_RESTORED" in output:
            logger.info("Restored client.keys from backup before starting agent")
        logger.info("Wazuh agent started via launchd")
    else:
        logger.error(f"Failed to start agent: {output}")
    return success


def restore_client_key_if_needed():
    """Restore client.keys from backup if it is missing, then restart the agent.

    Called when Wazuh is already installed (e.g. after a Resistine app
    reinstall) but client.keys was lost.  Returns True if the key was
    already present or was successfully restored; False on failure.

    Returns False without touching anything if the current user's email
    differs from the enrolled email — restoring a stale key from a
    different account would connect the agent to the wrong group.
    The caller (UI) is responsible for prompting a reinstall in that case.
    """
    if needs_reenrollment():
        logger.info("[WAZUH] Skipping key restore — enrolled under different email, reinstall required")
        return False

    if not os.path.exists(_KEY_BACKUP):
        logger.info("No client.keys backup found, nothing to restore")
        return True

    # Only restore and restart if client.keys is actually missing/empty.
    # Do not touch a running agent if the key is already in place.
    # Keychain is tried first (encrypted at rest); file backup is the fallback.
    script = (
        f"if [ ! -s '{_CLIENT_KEYS}' ]; then "
        f"  KC=$(security find-generic-password -k '{_KEYCHAIN}' -s '{_KC_SERVICE}' -a '{_KC_ACCOUNT}' -w 2>/dev/null); "
        f"  if [ -n \"$KC\" ]; then "
        f"    echo \"$KC\" > '{_CLIENT_KEYS}'; "
        f"  elif [ -s '{_KEY_BACKUP}' ]; then "
        f"    cp '{_KEY_BACKUP}' '{_CLIENT_KEYS}'; "
        f"  fi; "
        f"  if [ -s '{_CLIENT_KEYS}' ]; then "
        f"    chmod 640 '{_CLIENT_KEYS}' && chown root:wazuh '{_CLIENT_KEYS}' && "
        f"    launchctl bootout system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null; "
        f"    launchctl bootstrap system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null; "
        f"    echo KEY_RESTORED; "
        f"  fi; "
        f"else "
        f"  echo KEY_OK; "
        f"fi"
    )
    success, output = _run_privileged(script)
    if success:
        if "KEY_RESTORED" in output:
            logger.info("Restored client.keys from backup and restarted agent")
        else:
            logger.info("client.keys already present, agent untouched")
        return True
    logger.error(f"Failed to restore client.keys: {output}")
    return False


def _has_running_processes():
    """Return True if any wazuh-* daemon processes are running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "wazuh-agentd"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def stop_agent():
    """Stop the Wazuh agent completely.

    Uses a two-phase approach:
      1. ``launchctl bootout`` to unload the launchd service (if loaded).
      2. ``wazuh-control stop`` to terminate any daemon processes that
         were spawned outside launchd (e.g. by a previous install or
         manual ``wazuh-control start``).

    ``launchctl bootstrap`` does NOT adopt already-running processes,
    so bootout alone cannot kill orphaned daemons.  ``wazuh-control stop``
    reads the PID files in /Library/Ossec/var/run/ and sends SIGTERM
    directly to each daemon, which handles both cases reliably.
    """
    if not is_agent_installed():
        logger.info("Wazuh agent not installed, nothing to stop")
        return True

    # Phase 1: unload launchd service (prevents auto-restart)
    parts = []
    if _is_service_loaded():
        parts.append(f"launchctl bootout system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null")

    # Phase 2: wazuh-control stop kills daemons via their PID files,
    # then wait briefly for processes to exit after SIGTERM
    parts.append(f"'{_WAZUH_CONTROL}' stop 2>/dev/null")
    parts.append("sleep 2")
    # Ensure the script always exits 0 — we verify via _has_running_processes
    parts.append("true")

    script = "; ".join(parts)
    success, output = _run_privileged(script)
    logger.info(f"stop_agent: privileged script returned success={success} output={output!r}")

    # Verify processes are actually gone
    if _has_running_processes():
        logger.warning("Wazuh processes still running after stop, force-killing")
        kill_script = "pkill -9 -f '/Library/Ossec/bin/wazuh-' 2>/dev/null; true"
        _run_privileged(kill_script)

    stopped = not _has_running_processes()
    if stopped:
        logger.info("Wazuh agent stopped successfully")
    else:
        logger.error("Failed to stop all Wazuh processes")
    return stopped


_KEY_BACKUP = "/Library/Application Support/Resistine/wazuh_client.keys"
_CLIENT_KEYS = f"{WAZUH_INSTALL_DIR}/etc/client.keys"

# macOS System Keychain — primary secure storage for the agent key.
# The file backup (_KEY_BACKUP) is kept as a fallback and as an unprivileged
# sentinel so Python can cheaply decide whether to attempt a privileged restore.
_KEYCHAIN = "/Library/Keychains/System.keychain"
_KC_SERVICE = "com.resistine.wazuh.agent"
_KC_ACCOUNT = "client_key"


def remove_agent():
    """Stop the Wazuh agent and remove /Library/Ossec/ with admin privileges.

    Before wiping the install directory, the agent's client.keys is backed up
    to a persistent location outside /Library/Ossec/.  This preserves the
    manager-issued key so that reinstall can restore it and skip re-enrollment,
    avoiding duplicate-name conflicts on the manager.

    Returns True on success.
    """
    if not is_agent_installed() and not _is_service_loaded():
        logger.info("Wazuh agent not installed, nothing to remove")
        return True

    backup_dir = os.path.dirname(_KEY_BACKUP)
    # Stop all processes (launchd + wazuh-control + force-kill), back up
    # client.keys, then delete the install directory and plist.
    script = (
        f"launchctl bootout system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null; "
        f"'{_WAZUH_CONTROL}' stop 2>/dev/null; "
        f"pkill -9 -f '/Library/Ossec/bin/wazuh-' 2>/dev/null; "
        # Preserve the key in two places so reinstall can reconnect without
        # re-enrolling.  Keychain is the primary (encrypted at rest); the file
        # backup is a fallback and unprivileged sentinel for Python checks.
        f"mkdir -p '{backup_dir}' && "
        f"cp '{_CLIENT_KEYS}' '{_KEY_BACKUP}' 2>/dev/null && "
        f"security add-generic-password -U "
        f"-k '{_KEYCHAIN}' -s '{_KC_SERVICE}' -a '{_KC_ACCOUNT}' "
        f"-w \"$(cat '{_CLIENT_KEYS}')\" 2>/dev/null; "
        f"rm -rf '{WAZUH_INSTALL_DIR}'; "
        f"rm -f '{WAZUH_LAUNCHD_PLIST}'"
    )
    success, output = _run_privileged(script)
    if success:
        logger.info("Wazuh agent removed successfully")
    else:
        logger.error(f"Failed to remove Wazuh agent: {output}")
    return success


def full_install(progress_callback=None):
    """Orchestrate the complete install flow: download, write env, install, start.

    Combines install + start into a **single** privileged osascript call so
    the user only sees one password prompt instead of two.
    """
    # 1. Download
    if progress_callback:
        progress_callback("Downloading Wazuh agent...")
    pkg_path = download_package(progress_callback)
    if not pkg_path:
        if progress_callback:
            progress_callback("Download failed")
        return False

    # 2. Ensure the agent group exists on the manager, then write the env file.
    agent_name = get_agent_name()
    agent_group = get_agent_group()

    if progress_callback:
        progress_callback(f"Creating agent group '{agent_group}'...")
    if not create_wazuh_group(agent_group):
        logger.warning(f"[WAZUH] Could not create group '{agent_group}', falling back to 'default'")
        agent_group = "default"

    if not write_env_file(agent_name, agent_group):
        if progress_callback:
            progress_callback("Failed to write environment file")
        return False

    # 3. Install the package AND start the agent in a single privileged call.
    #    This avoids a second osascript password dialog.  The script:
    #      a) Runs the installer — if this fails we capture INSTALL_FAIL
    #      b) Directly patches <agent_name> in ossec.conf to our UUID-suffixed
    #         name.  The installer reads the env file but its behavior is
    #         unreliable; patching ossec.conf post-install is the authoritative
    #         way to set the name.
    #      c) Registers with the manager using agent-auth to populate
    #         client.keys.  When client.keys is populated, wazuh-agentd
    #         connects directly without going through auto-enrollment.
    #         If a duplicate agent name exists on the manager, delete it
    #         via the Wazuh REST API before enrolling.
    #      d) Bootstraps the launchd plist so launchd manages all processes.
    #    We use launchctl bootstrap (not wazuh-control start) so that all
    #    agent processes live under launchd's supervision.  This ensures
    #    bootout can cleanly terminate them later without orphans.
    if progress_callback:
        progress_callback("Installing Wazuh agent (admin password required)...")

    ossec_conf = f"{WAZUH_INSTALL_DIR}/etc/ossec.conf"
    plist = WAZUH_LAUNCHD_PLIST
    agent_auth = f"{WAZUH_INSTALL_DIR}/bin/agent-auth"
    backup_dir = os.path.dirname(_KEY_BACKUP)
    install_and_start_script = (
        f"installer -pkg '{pkg_path}' -target / || echo INSTALL_FAIL; "
        # Patch agent_name directly in ossec.conf — more reliable than the
        # env file, which the installer may ignore or read inconsistently.
        f"sed -i '' 's|<agent_name>.*</agent_name>|<agent_name>{agent_name}</agent_name>|' '{ossec_conf}'; "
        # Always re-enroll with agent-auth so the agent is placed in the
        # correct group on the manager.  Restoring a stale key would
        # reconnect with the old enrollment (possibly wrong group), so we
        # clear it first regardless of whether this is a fresh install or
        # a reinstall.  This covers every edge case: fresh install,
        # reinstall after uninstall, and reinstall after app reinstall.
        f"rm -f '{_CLIENT_KEYS}'; "
        f"'{agent_auth}' -m '{WAZUH_MANAGER}' -A '{agent_name}' -G '{agent_group}' && echo KEY_ENROLLED || echo ENROLL_FAILED; "
        # Persist the newly issued key to Keychain + file backup so that
        # restore_client_key_if_needed() can reconnect after a future app
        # reinstall without needing another password prompt.
        f"if [ -s '{_CLIENT_KEYS}' ]; then "
        f"  mkdir -p '{backup_dir}' && cp '{_CLIENT_KEYS}' '{_KEY_BACKUP}'; "
        f"  security add-generic-password -U "
        f"  -k '{_KEYCHAIN}' -s '{_KC_SERVICE}' -a '{_KC_ACCOUNT}' "
        f"  -w \"$(cat '{_CLIENT_KEYS}')\" 2>/dev/null; "
        f"fi; "
        f"launchctl bootout system '{plist}' 2>/dev/null; "
        f"launchctl bootstrap system '{plist}' 2>/dev/null; "
        f"echo DONE"
    )
    logger.info("Running privileged install+start script")
    success, output = _run_privileged(install_and_start_script, timeout=300)
    logger.info(f"install+start output: {output!r}")

    # The osascript call itself may fail (user cancelled the dialog, timeout).
    # However, a timeout doesn't necessarily mean the install failed — the
    # installer may have finished in the background.  Check the disk before
    # giving up.
    if not success:
        if is_agent_installed():
            logger.warning(f"Privileged call reported failure ({output}), but agent binary exists on disk — treating as success")
        else:
            logger.error(f"Privileged call failed: {output or 'user cancelled'}")
            if progress_callback:
                progress_callback("Installation failed")
            return False

    # Check if the installer step itself failed
    if "INSTALL_FAIL" in output:
        logger.error(f"Installer command failed: {output}")
        if progress_callback:
            progress_callback("Installation failed")
        return False

    # Verify the agent is actually running via launchd
    if get_agent_status() == "Running":
        logger.info("Wazuh agent installed and running via launchd")
        if progress_callback:
            progress_callback("Wazuh agent installed and running")
    else:
        logger.warning("Agent installed but not yet running")
        if progress_callback:
            progress_callback("Wazuh agent installed (agent may need manual start)")

    # Record which email this enrollment belongs to so we can detect
    # account changes (different user / org) on future startups.
    settings.set("wazuh", "enrolled_email", settings.get("auth", "email", ""))

    logger.info("Wazuh full install completed successfully")
    return True

"""
sudo /Library/Ossec/bin/wazuh-control restart
Check status:


sudo /Library/Ossec/bin/wazuh-control status
Check logs for the actual error:


sudo tail -50 /Library/Ossec/logs/ossec.log
Run the log command first — paste the output here and I can tell you exactly what's wrong.
"""