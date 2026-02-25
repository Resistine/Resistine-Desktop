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


def get_agent_name():
    """Return the machine hostname to use as the Wazuh agent name."""
    return socket.gethostname()


def get_agent_group():
    """Return the user's email (sanitized) as the agent group."""
    email = settings.get("auth", "email", "default")
    return email.replace("@", ".")


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
    """
    if _is_service_loaded():
        logger.info("Wazuh launchd service already loaded, nothing to do")
        return True

    script = f"launchctl bootstrap system '{WAZUH_LAUNCHD_PLIST}'"
    success, output = _run_privileged(script)
    if success:
        logger.info("Wazuh agent started via launchd")
    else:
        logger.error(f"Failed to start agent: {output}")
    return success


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


def remove_agent():
    """Stop the Wazuh agent and remove /Library/Ossec/ with admin privileges.

    Returns True on success.
    """
    if not is_agent_installed() and not _is_service_loaded():
        logger.info("Wazuh agent not installed, nothing to remove")
        return True

    # Stop all processes (launchd + wazuh-control + force-kill),
    # then delete the install directory and plist.
    script = (
        f"launchctl bootout system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null; "
        f"'{_WAZUH_CONTROL}' stop 2>/dev/null; "
        f"pkill -9 -f '/Library/Ossec/bin/wazuh-' 2>/dev/null; "
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

    # 2. Write env file (unprivileged — /tmp is world-writable)
    agent_name = get_agent_name()
    agent_group = get_agent_group()
    if not write_env_file(agent_name, agent_group):
        if progress_callback:
            progress_callback("Failed to write environment file")
        return False

    # 3. Install the package AND start the agent in a single privileged call.
    #    This avoids a second osascript password dialog.  The script:
    #      a) Runs the installer — if this fails we capture INSTALL_FAIL
    #      b) Bootstraps the launchd plist so launchd manages all processes
    #    We use launchctl bootstrap (not wazuh-control start) so that all
    #    agent processes live under launchd's supervision.  This ensures
    #    bootout can cleanly terminate them later without orphans.
    if progress_callback:
        progress_callback("Installing Wazuh agent (admin password required)...")

    plist = WAZUH_LAUNCHD_PLIST
    install_and_start_script = (
        f"installer -pkg '{pkg_path}' -target / || echo INSTALL_FAIL; "
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

    logger.info("Wazuh full install completed successfully")
    return True
