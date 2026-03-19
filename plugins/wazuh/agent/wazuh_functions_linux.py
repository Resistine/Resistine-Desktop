"""
Wazuh Agent Functions for Linux
Handles download, install, start/stop of the Wazuh SIEM agent using systemd and package managers.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import platform
import socket
import subprocess
import tempfile
import re

from utils import settings
from utils.logger import logger
from gui.dialogs import CTkPasswordDialog

from plugins.wazuh.config import (
    LINUX_WAZUH_DEB_URL,
    LINUX_WAZUH_RPM_URL,
    LINUX_PKG_ARCH_MAP_DEB,
    LINUX_PKG_ARCH_MAP_RPM,
    WAZUH_MANAGER,
    LINUX_WAZUH_DIR,
)

def run_privileged_command(command, timeout=120):
    """
    Run a command with elevated privileges using pkexec or sudo.
    Shows the password dialog if sudo is used.
    Returns (success, output).
    """
    logger.info(f"Attempting to run with pkexec: {command}")
    try:
        result = subprocess.run(
            ["pkexec"] + command, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            logger.warning(
                f"pkexec failed (code {result.returncode}): {result.stderr.strip()}. Falling back to sudo."
            )
    except FileNotFoundError:
        logger.warning("pkexec not found, falling back to sudo")
    except Exception as e:
        logger.warning(f"Error running pkexec: {e}")

    logger.info("Falling back to sudo with themed password prompt")
    import tkinter as tk
    try:
        root = tk._default_root
    except:
        root = None
    
    dialog = CTkPasswordDialog(title="Authentication Required", text="Enter password to modify Wazuh Agent settings:")
    password = dialog.get_input()

    if not password:
        logger.error("User cancelled password prompt")
        return False, "User cancelled"

    try:
        # Pass password to sudo via standard input
        sudo_command = ["sudo", "-S", "-p", ""] + command
        result = subprocess.run(
            sudo_command,
            input=password + "\n",
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            logger.error(f"sudo failed: {result.stderr.strip() + result.stdout.strip()}")
            return False, result.stderr.strip() + result.stdout.strip()
    except Exception as e:
        logger.error(f"Error executing command with sudo: {e}")
        return False, str(e)


def _get_machine_id():
    """Return the Linux machine ID."""
    for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return None

def get_agent_name():
    """Return a stable, org-unique agent name."""
    hostname = socket.gethostname()
    machine_id = _get_machine_id()
    if machine_id:
        suffix = machine_id.replace("-", "")[-12:].upper()
        name = f"{hostname}-{suffix}"
    else:
        name = hostname
    return re.sub(r"[^A-Za-z0-9.\-_]", "", name)

def get_agent_group():
    email = settings.get("auth", "email", "default")
    if email and email != "default":
        return email.replace("@", ".")
    return "default"

def needs_reenrollment():
    enrolled = settings.get("wazuh", "enrolled_email", "")
    current = settings.get("auth", "email", "")
    if enrolled and current and enrolled != current:
        return True
    return False

def _get_os_info():
    """Determine if OS is DEB or RPM based."""
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
            if "debian" in content or "ubuntu" in content:
                return "deb"
            if "fedora" in content or "centos" in content or "rhel" in content or "red hat" in content:
                return "rpm"
    except Exception:
        pass
    
    # Fallback checking commands
    if subprocess.run(["which", "dpkg"], capture_output=True).returncode == 0:
        return "deb"
    if subprocess.run(["which", "rpm"], capture_output=True).returncode == 0:
        return "rpm"
    return None

def get_package_url():
    arch = platform.machine()
    os_type = _get_os_info()
    if os_type == "deb":
        arch_suffix = LINUX_PKG_ARCH_MAP_DEB.get(arch, "amd64")
        return LINUX_WAZUH_DEB_URL.format(arch=arch_suffix)
    elif os_type == "rpm":
        arch_suffix = LINUX_PKG_ARCH_MAP_RPM.get(arch, "x86_64")
        return LINUX_WAZUH_RPM_URL.format(arch=arch_suffix)
    return None

def is_agent_installed():
    return os.path.exists(LINUX_WAZUH_DIR)

def get_agent_status():
    if not is_agent_installed():
        return "Not Installed"
    
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "wazuh-agent"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.stdout.strip() == "active":
            return "Running"
    except Exception as e:
        logger.warning(f"Could not check wazuh-agent status: {e}")
        
    # Check processes
    try:
        result = subprocess.run(
            ["pgrep", "-x", "wazuh-agentd"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "Running"
    except Exception:
        pass
        
    return "Stopped"

def download_package(progress_callback=None):
    url = get_package_url()
    if not url:
        logger.error("Unsupported OS type or architecture for Wazuh install")
        return None
        
    tmp_dir = tempfile.mkdtemp(prefix="wazuh_")
    filename = url.split("/")[-1]
    pkg_path = os.path.join(tmp_dir, filename)

    if progress_callback:
        progress_callback("Downloading Wazuh agent...")

    logger.info(f"Downloading Wazuh package from {url}")
    try:
        result = subprocess.run(
            ["curl", "-fSL", "-o", pkg_path, url],
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
    # Not using env file for Linux, we'll pass via environment to the installer or patch ossec.conf
    pass

_KEY_BACKUP = os.path.expanduser("~/.config/resistine/wazuh_client.keys")
_CLIENT_KEYS = f"{LINUX_WAZUH_DIR}/etc/client.keys"

def start_agent():
    if get_agent_status() == "Running":
        return True
        
    # Restore key if missing
    if os.path.exists(_KEY_BACKUP):
        script = f"""
        if [ ! -s '{_CLIENT_KEYS}' ]; then
            if [ -s '{_KEY_BACKUP}' ]; then
                cp '{_KEY_BACKUP}' '{_CLIENT_KEYS}'
                chmod 640 '{_CLIENT_KEYS}'
                chown wazuh:wazuh '{_CLIENT_KEYS}' || chown root:wazuh '{_CLIENT_KEYS}'
            fi
        fi
        systemctl enable wazuh-agent
        systemctl start wazuh-agent
        """
        success, output = run_privileged_command(["sh", "-c", script])
        return success
    else:
        success, output = run_privileged_command(["systemctl", "start", "wazuh-agent"])
        return success

def restore_client_key_if_needed():
    if needs_reenrollment():
        return False
        
    if not os.path.exists(_KEY_BACKUP):
        return True
        
    script = f"""
        if [ ! -s '{_CLIENT_KEYS}' ]; then
            if [ -s '{_KEY_BACKUP}' ]; then
                cp '{_KEY_BACKUP}' '{_CLIENT_KEYS}'
                chmod 640 '{_CLIENT_KEYS}'
                chown wazuh:wazuh '{_CLIENT_KEYS}' || chown root:wazuh '{_CLIENT_KEYS}'
                systemctl restart wazuh-agent
                echo KEY_RESTORED
            fi
        fi
        """
    success, output = run_privileged_command(["sh", "-c", script])
    return success

def stop_agent():
    if not is_agent_installed():
        return True
        
    success, output = run_privileged_command(["systemctl", "stop", "wazuh-agent"])
    
    # Verify stopped
    try:
        if subprocess.run(["pgrep", "-x", "wazuh-agentd"], capture_output=True).returncode == 0:
            run_privileged_command(["pkill", "-9", "-f", f"{LINUX_WAZUH_DIR}/bin/wazuh-"])
    except:
        pass
        
    return get_agent_status() != "Running"

def remove_agent():
    if not is_agent_installed():
        return True
        
    os_type = _get_os_info()
    backup_dir = os.path.dirname(_KEY_BACKUP)
    
    uninstall_cmd = ""
    if os_type == "deb":
        uninstall_cmd = "apt-get remove -y wazuh-agent"
    elif os_type == "rpm":
        uninstall_cmd = "yum remove -y wazuh-agent || dnf remove -y wazuh-agent"
        
    script = f"""
        systemctl stop wazuh-agent 2>/dev/null
        mkdir -p '{backup_dir}'
        cp '{_CLIENT_KEYS}' '{_KEY_BACKUP}' 2>/dev/null
        chown {os.getuid()}:{os.getgid()} '{_KEY_BACKUP}' 2>/dev/null
        {uninstall_cmd}
        rm -rf '{LINUX_WAZUH_DIR}'
    """
    success, output = run_privileged_command(["sh", "-c", script])
    return success

def full_install(progress_callback=None):
    pkg_path = download_package(progress_callback)
    if not pkg_path:
        if progress_callback: progress_callback("Download failed")
        return False
        
    agent_name = get_agent_name()
    agent_group = get_agent_group()
    
    import requests
    url = "https://validate.resistine.work/create-groups"
    try:
        requests.post(url, params={"name": agent_group}, timeout=30)
    except:
        agent_group = "default"
        
    os_type = _get_os_info()
    install_cmd = ""
    if os_type == "deb":
        install_cmd = f"WAZUH_MANAGER='{WAZUH_MANAGER}' WAZUH_AGENT_NAME='{agent_name}' WAZUH_AGENT_GROUP='{agent_group}' dpkg -i '{pkg_path}'"
    elif os_type == "rpm":
        install_cmd = f"WAZUH_MANAGER='{WAZUH_MANAGER}' WAZUH_AGENT_NAME='{agent_name}' WAZUH_AGENT_GROUP='{agent_group}' rpm -ihv '{pkg_path}'"

    ossec_conf = f"{LINUX_WAZUH_DIR}/etc/ossec.conf"
    agent_auth = f"{LINUX_WAZUH_DIR}/bin/agent-auth"
    backup_dir = os.path.dirname(_KEY_BACKUP)
    
    can_restore = (not needs_reenrollment()) and os.path.exists(_KEY_BACKUP)
    
    if can_restore:
        enrollment_script = f"""
            if [ -s '{_KEY_BACKUP}' ]; then
                cp '{_KEY_BACKUP}' '{_CLIENT_KEYS}'
                chmod 640 '{_CLIENT_KEYS}'
            else
                rm -f '{_CLIENT_KEYS}'
                '{agent_auth}' -m '{WAZUH_MANAGER}' -A '{agent_name}' -G '{agent_group}'
                mkdir -p '{backup_dir}' && cp '{_CLIENT_KEYS}' '{_KEY_BACKUP}'
                chown {os.getuid()}:{os.getgid()} '{_KEY_BACKUP}' 2>/dev/null
            fi
        """
    else:
        enrollment_script = f"""
            rm -f '{_CLIENT_KEYS}'
            '{agent_auth}' -m '{WAZUH_MANAGER}' -A '{agent_name}' -G '{agent_group}'
            mkdir -p '{backup_dir}' && cp '{_CLIENT_KEYS}' '{_KEY_BACKUP}'
            chown {os.getuid()}:{os.getgid()} '{_KEY_BACKUP}' 2>/dev/null
        """

    script = f"""
        {install_cmd}
        sed -i 's|<agent_name>.*</agent_name>|<agent_name>{agent_name}</agent_name>|' '{ossec_conf}'
        {enrollment_script}
        systemctl daemon-reload
        systemctl enable wazuh-agent
        systemctl restart wazuh-agent
    """
    
    if progress_callback:
        progress_callback("Installing Wazuh agent (admin password required)...")
        
    success, output = run_privileged_command(["sh", "-c", script])
    
    if success or is_agent_installed():
        settings.set("wazuh", "enrolled_email", settings.get("auth", "email", ""))
        if progress_callback:
            progress_callback("Wazuh agent installed and running")
        return True
        
    if progress_callback:
        progress_callback("Installation failed")
    return False
