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
    WAZUH_AGENT_CONTROL,
    WAZUH_BASE_URL,
    WAZUH_ENV_FILE,
    WAZUH_LAUNCHD_PLIST,
    WAZUH_MANAGER,
    WAZUH_PKG_ARCH_MAP,
    WAZUH_VERSION,
)


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
    normal users, so ``os.path.exists(WAZUH_AGENT_CONTROL)`` returns False
    even when the file is present.  Instead we check for the directory itself
    (os.path.isdir succeeds without read permission) or the launchd plist
    which is world-readable.
    """
    return os.path.isdir("/Library/Ossec") or os.path.exists(WAZUH_LAUNCHD_PLIST)


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
        logger.info("_run_privileged: executing osascript")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        logger.info(f"_run_privileged: returncode={result.returncode} stdout={stdout!r} stderr={stderr!r}")
        output = stdout or stderr
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


def install_package(pkg_path, progress_callback=None):
    """Install the .pkg with admin privileges.

    Returns True on success.
    """
    if progress_callback:
        progress_callback("Installing Wazuh agent (admin password required)...")

    script = f"installer -pkg '{pkg_path}' -target /"
    success, output = _run_privileged(script)
    if not success:
        logger.error(f"Installation failed: {output}")
    else:
        logger.info("Wazuh agent installed successfully")
    return success


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
    """Start the Wazuh agent and ensure the launchd service is loaded.

    Bootstraps the launchd plist (if not already loaded) so the agent
    auto-starts on reboot, then starts the agent via wazuh-control.
    """
    parts = []

    # Ensure the launchd service is registered for auto-start on reboot
    if not _is_service_loaded():
        parts.append(f"launchctl bootstrap system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null")

    # Start the agent processes
    parts.append(f"'{WAZUH_AGENT_CONTROL}' start")

    script = "; ".join(parts)
    success, output = _run_privileged(script)
    if success:
        logger.info("Wazuh agent started (launchd service ensured)")
    else:
        logger.error(f"Failed to start agent: {output}")
    return success


def stop_agent():
    """Stop the Wazuh agent via wazuh-control or launchctl bootout."""
    if is_agent_installed():
        script = f"'{WAZUH_AGENT_CONTROL}' stop"
    elif _is_service_loaded():
        script = f"launchctl bootout system '{WAZUH_LAUNCHD_PLIST}'"
    else:
        logger.info("Wazuh agent service is not loaded, nothing to stop")
        return True
    success, output = _run_privileged(script)
    if success:
        logger.info("Wazuh agent stopped")
    else:
        logger.error(f"Failed to stop agent: {output}")
    return success


def remove_agent():
    """Stop the Wazuh agent and remove /Library/Ossec/ with admin privileges.

    Returns True on success.
    """
    if not is_agent_installed() and not _is_service_loaded():
        logger.info("Wazuh agent not installed, nothing to remove")
        return True

    # Stop the agent, unload the service, delete the install directory and plist
    script = (
        f"'{WAZUH_AGENT_CONTROL}' stop 2>/dev/null; "
        f"launchctl bootout system '{WAZUH_LAUNCHD_PLIST}' 2>/dev/null; "
        "rm -rf /Library/Ossec; "
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
    #      b) Starts the agent (harmless if postinstall already started it)
    #      c) Prints a status marker so we can parse the outcome from stdout
    #    We intentionally end with `echo` so the overall exit code is 0 and
    #    osascript does not report a spurious failure from wazuh-control.
    if progress_callback:
        progress_callback("Installing Wazuh agent (admin password required)...")

    ctrl = WAZUH_AGENT_CONTROL
    plist = WAZUH_LAUNCHD_PLIST
    install_and_start_script = (
        f"installer -pkg '{pkg_path}' -target / || echo INSTALL_FAIL; "
        f"launchctl bootstrap system '{plist}' 2>/dev/null; "
        f"'{ctrl}' start 2>/dev/null; "
        f"'{ctrl}' status 2>/dev/null; "
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

    # The agent is installed.  Check if it's running from wazuh-control
    # status output embedded in the combined stdout.
    if "is running" in output.lower():
        logger.info("Wazuh agent installed and running (single privileged call)")
        if progress_callback:
            progress_callback("Wazuh agent installed and running")
    else:
        logger.warning(f"Agent installed, start may have failed: {output}")
        if progress_callback:
            progress_callback("Wazuh agent installed (agent may need manual start)")

    logger.info("Wazuh full install completed successfully")
    return True
