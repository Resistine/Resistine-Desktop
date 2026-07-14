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
import urllib.error
import urllib.request

from utils import settings
from utils.logger import logger
from gui.dialogs import CTkPasswordDialog

from plugins.wazuh.config import (
    LINUX_WAZUH_DEB_URL,
    LINUX_WAZUH_RPM_URL,
    LINUX_PKG_ARCH_MAP_DEB,
    LINUX_PKG_ARCH_MAP_RPM,
    WAZUH_MANAGER,
    WAZUH_MANAGER_PORT,
    WAZUH_PROTOCOL,
    WAZUH_REGISTRATION_PORT,
    LINUX_WAZUH_DIR,
)

# Deployment-variable prefix passed to the package installer.  Carries the
# manager address, ports, protocol, agent name, and group so the package's
# preinstall hook patches ossec.conf accordingly.
def _deploy_env(agent_name, agent_group):
    return (
        f"WAZUH_MANAGER='{WAZUH_MANAGER}' "
        f"WAZUH_MANAGER_PORT='{WAZUH_MANAGER_PORT}' "
        f"WAZUH_PROTOCOL='{WAZUH_PROTOCOL}' "
        f"WAZUH_REGISTRATION_SERVER='{WAZUH_MANAGER}' "
        f"WAZUH_REGISTRATION_PORT='{WAZUH_REGISTRATION_PORT}' "
        f"WAZUH_AGENT_NAME='{agent_name}' "
        f"WAZUH_AGENT_GROUP='{agent_group}'"
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
    """Return the user's email with '@' replaced by '-' to match the
    canonical group name created by /verify-otp.
    """
    email = settings.get("auth", "email", "default")
    if email and email != "default":
        return email.replace("@", "-")
    return "default"

def needs_reenrollment():
    enrolled = settings.get("wazuh", "enrolled_email", "")
    current = settings.get("auth", "email", "")
    if enrolled and current and enrolled != current:
        return True
    return False

def _get_os_info():
    """Determine package family (deb, rpm, arch) using LinuxDistro utility.

    openSUSE/SLES is rpm-based — it uses the same .rpm artifact and the same
    ``rpm -ihv`` install path as Fedora — so it maps to "rpm".  remove_agent
    picks the correct uninstall tool (zypper vs dnf/yum) from the detected
    package manager independently, so it doesn't need its own family here.
    """
    from utils.distro import LinuxDistro
    if LinuxDistro.is_debian_like():
        return "deb"
    if LinuxDistro.is_fedora_like() or LinuxDistro.is_suse_like():
        return "rpm"
    if LinuxDistro.is_arch_like():
        return "arch"
    return None

def get_package_url():
    arch = platform.machine()
    os_type = _get_os_info()
    if os_type == "deb":
        arch_suffix = LINUX_PKG_ARCH_MAP_DEB.get(arch, "amd64")
        return LINUX_WAZUH_DEB_URL.format(arch=arch_suffix)
    elif os_type == "rpm" or os_type == "arch":
        # Arch uses the RPM artifact and extracts it with bsdtar (libarchive); upstream Wazuh ships no pacman package
        arch_suffix = LINUX_PKG_ARCH_MAP_RPM.get(arch, "x86_64")
        return LINUX_WAZUH_RPM_URL.format(arch=arch_suffix)
    elif os_type == "arch":
        # Wazuh doesn't have an official Arch package, usually installed via AUR
        # or we might need a specific handling. For now, mark as unsupported.
        return None
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
        urllib.request.urlretrieve(url, pkg_path)
        logger.info(f"Downloaded to {pkg_path}")
        return pkg_path
    except urllib.error.HTTPError as e:
        logger.error(f"Download failed: HTTP {e.code} {e.reason}")
        return None
    except urllib.error.URLError as e:
        logger.error(f"Download failed: {e.reason}")
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

def write_env_file(agent_name, agent_group):
    # Not using env file for Linux, we'll pass via environment to the installer or patch ossec.conf
    pass

_KEY_BACKUP = os.path.expanduser("~/.config/resistine/wazuh_client.keys")
_CLIENT_KEYS = f"{LINUX_WAZUH_DIR}/etc/client.keys"

# --- Passwordless re-enrollment helper (polkit) -----------------------------
# Mirrors the VPN helper: a root-owned script that ONLY re-enrolls the Wazuh
# agent (agent-auth + restart), authorized via a polkit action with
# allow_active=yes so the re-registration loop can re-enroll silently (no
# password prompt every 15s). Installed once (one admin prompt).
WAZUH_HELPER_DIR = "/usr/local/lib/resistine"
WAZUH_HELPER_PATH = f"{WAZUH_HELPER_DIR}/resistine-wazuh-helper"
WAZUH_POLKIT_ACTION_ID = "com.resistine.wazuh.control"
WAZUH_POLKIT_POLICY_PATH = (
    f"/usr/share/polkit-1/actions/{WAZUH_POLKIT_ACTION_ID}.policy"
)

# name/group are validated here AND in the helper — Wazuh's own allowed charset.
_SAFE_ARG_RE = re.compile(r"^[A-Za-z0-9.\-_]+$")

WAZUH_HELPER_SCRIPT = r"""#!/bin/sh
# Resistine Wazuh helper. Two actions, both root-owned and authorized via polkit
# action com.resistine.wazuh.control (passwordless for the active local
# session): 'state' prints the agentd state file (root-readable only), and
# 'reenroll' re-registers the agent with the manager and restarts it.
set -eu

ACTION="${1:-}"

MANAGER="__MANAGER__"
REG_PORT="__REG_PORT__"
CLIENT_KEYS="__CLIENT_KEYS__"
AGENT_AUTH="__AGENT_AUTH__"
STATE_FILE="__STATE_FILE__"

case "$ACTION" in
    state)
        # Print the state file so the app can read connection status silently.
        cat "$STATE_FILE" 2>/dev/null || true
        ;;
    reenroll)
        NAME="${2:-}"
        GROUP="${3:-}"
        # Only Wazuh's safe agent-name/group charset (no shell metacharacters).
        for v in "$NAME" "$GROUP"; do
            case "$v" in
                *[!A-Za-z0-9._-]*|"") echo "invalid name/group" >&2; exit 2 ;;
            esac
        done
        rm -f "$CLIENT_KEYS"
        "$AGENT_AUTH" -m "$MANAGER" -P "$REG_PORT" -A "$NAME" -G "$GROUP"
        systemctl restart wazuh-agent
        ;;
    *)
        echo "usage: resistine-wazuh-helper {state|reenroll <name> <group>}" >&2
        exit 1
        ;;
esac
"""

WAZUH_HELPER_POLICY = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1.0/policyconfig.dtd">
<policyconfig>
  <vendor>Resistine</vendor>
  <action id="{WAZUH_POLKIT_ACTION_ID}">
    <description>Re-enroll the Resistine SIEM agent</description>
    <message>Authentication is required to re-enroll the Resistine SIEM agent</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>yes</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">{WAZUH_HELPER_PATH}</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
"""

_wazuh_helper_install_attempted = False


def _wazuh_helper_script_filled():
    """The helper script with install-specific constants substituted in."""
    return (
        WAZUH_HELPER_SCRIPT
        .replace("__MANAGER__", WAZUH_MANAGER)
        .replace("__REG_PORT__", str(WAZUH_REGISTRATION_PORT))
        .replace("__CLIENT_KEYS__", _CLIENT_KEYS)
        .replace("__AGENT_AUTH__", f"{LINUX_WAZUH_DIR}/bin/agent-auth")
        .replace("__STATE_FILE__", f"{LINUX_WAZUH_DIR}/var/run/wazuh-agentd.state")
    )


def wazuh_helper_installed():
    return os.path.exists(WAZUH_HELPER_PATH) and os.path.exists(WAZUH_POLKIT_POLICY_PATH)


def install_wazuh_helper():
    """Install the root-owned re-enroll helper + polkit policy (one prompt)."""
    if wazuh_helper_installed():
        return True
    import base64
    h64 = base64.b64encode(_wazuh_helper_script_filled().encode()).decode()
    p64 = base64.b64encode(WAZUH_HELPER_POLICY.encode()).decode()
    script = (
        "set -e\n"
        f"mkdir -p '{WAZUH_HELPER_DIR}'\n"
        f"printf %s '{h64}' | base64 -d > '{WAZUH_HELPER_PATH}'\n"
        f"chown root:root '{WAZUH_HELPER_PATH}'\n"
        f"chmod 755 '{WAZUH_HELPER_PATH}'\n"
        f"printf %s '{p64}' | base64 -d > '{WAZUH_POLKIT_POLICY_PATH}'\n"
        f"chown root:root '{WAZUH_POLKIT_POLICY_PATH}'\n"
        f"chmod 644 '{WAZUH_POLKIT_POLICY_PATH}'\n"
    )
    success, _ = run_privileged_command(["sh", "-c", script])
    if success:
        logger.info("Installed passwordless Wazuh re-enroll helper + polkit policy")
    else:
        logger.warning("Failed to install Wazuh re-enroll helper")
    return success


def _classify_enroll_output(output, name):
    """Turn raw agent-auth output into an actionable one-line message, or None."""
    low = (output or "").lower()
    if "unable to add agent" in low or "invalid request for new agent" in low:
        return (
            f"Manager rejected: an agent named '{name}' already exists. Remove it "
            "on the dashboard (or enable forced re-registration on the manager). "
            "Retrying every 15s."
        )
    if any(s in low for s in (
        "unable to connect", "couldn't connect", "cannot connect",
        "timeout", "connection refused",
    )):
        return "Couldn't reach the manager to enroll — check VPN/network. Retrying."
    if "duplicate" in low:
        return f"Manager rejected a duplicate for '{name}'. Remove the old agent server-side."
    return None


def reenroll_agent():
    """Re-register the agent with the manager (agent-auth) and restart it.

    Returns ``(success, message)`` — message is a human-readable, actionable
    status (the manager commonly rejects a still-present duplicate agent).

    Used by the re-registration loop when the agent is running but not connected
    (e.g. the server dropped/replaced its key). Uses the passwordless helper
    when available so the loop doesn't prompt every retry; otherwise falls back
    to a single prompted privileged run.
    """
    name = get_agent_name()
    group = get_agent_group()
    if not (_SAFE_ARG_RE.match(name) and _SAFE_ARG_RE.match(group)):
        logger.error(f"[WAZUH] refusing re-enroll with unsafe name/group: {name!r}/{group!r}")
        return False, "Refusing re-enroll: unsafe agent name/group."

    global _wazuh_helper_install_attempted
    if wazuh_helper_installed() or (
        not _wazuh_helper_install_attempted and install_wazuh_helper()
    ):
        _wazuh_helper_install_attempted = True
        result = subprocess.run(
            ["pkexec", WAZUH_HELPER_PATH, "reenroll", name, group],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, "Re-registration submitted."
        combined = f"{result.stderr or ''}\n{result.stdout or ''}".strip()
        logger.error(f"[WAZUH] re-enroll helper failed: {combined}")
        return False, _classify_enroll_output(combined, name) or "Re-registration failed — see logs."

    _wazuh_helper_install_attempted = True
    # Fallback: single prompted re-enroll.
    agent_auth = f"{LINUX_WAZUH_DIR}/bin/agent-auth"
    script = (
        f"rm -f '{_CLIENT_KEYS}'\n"
        f"'{agent_auth}' -m '{WAZUH_MANAGER}' -P '{WAZUH_REGISTRATION_PORT}' "
        f"-A '{name}' -G '{group}'\n"
        f"systemctl restart wazuh-agent\n"
    )
    success, output = run_privileged_command(["sh", "-c", script])
    if success:
        return True, "Re-registration submitted."
    logger.error(f"[WAZUH] re-enroll failed: {output}")
    return False, _classify_enroll_output(output, name) or "Re-registration failed — see logs."


def get_connection_state():
    """Return the agent's manager-connection status (see connection_state).

    Tries a direct read first; the agentd state file is usually root:wazuh 0640
    (unreadable by the app user), so when that yields UNKNOWN and the
    passwordless helper is installed, read it silently via 'pkexec helper state'.
    """
    from plugins.wazuh.agent import connection_state as cs

    state = cs.get_connection_state()
    if state != cs.UNKNOWN:
        return state

    if wazuh_helper_installed():
        try:
            result = subprocess.run(
                ["pkexec", WAZUH_HELPER_PATH, "state"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return cs.parse_state(result.stdout)
        except Exception as e:
            logger.debug(f"[WAZUH] helper state read failed: {e}")
    return cs.UNKNOWN

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

def agent_present(wipe_keys: bool = False) -> bool:
    """Return True if there's a Wazuh agent (or key backup) worth removing.

    Mirrors remove_agent's guard so callers batching privileged work (e.g. the
    app uninstaller) can decide whether to include the teardown commands.
    """
    return is_agent_installed() or (wipe_keys and os.path.exists(_KEY_BACKUP))


def build_remove_script(wipe_keys: bool = False) -> str:
    """Build the privileged shell script that tears down the Wazuh agent.

    Split out from remove_agent so the app-level uninstaller can fold these
    commands into a single privilege-escalation prompt instead of running its
    own. See remove_agent for the per-distro rationale.
    """
    from utils.distro import LinuxDistro

    os_type = _get_os_info()
    pkg_mgr = LinuxDistro.get_package_manager()
    backup_dir = os.path.dirname(_KEY_BACKUP)

    # --- Stop + disable the service (init-system aware) ---
    # wazuh-control stops the agent regardless of init system; the unit/init
    # script teardown then differs between systemd and OpenRC/SysV.
    stop_cmd = f"'{LINUX_WAZUH_DIR}/bin/wazuh-control' stop 2>/dev/null || true"
    if LinuxDistro.is_systemd():
        service_teardown = (
            "systemctl stop wazuh-agent || true; "
            "systemctl disable wazuh-agent || true; "
            "rm -f /usr/lib/systemd/system/wazuh-agent.service "
            "/etc/systemd/system/wazuh-agent.service; "
            "systemctl daemon-reload || true"
        )
    else:
        # OpenRC (rc-service/rc-update) or SysV (service) fallback.
        service_teardown = (
            "(rc-service wazuh-agent stop 2>/dev/null || "
            "service wazuh-agent stop 2>/dev/null) || true; "
            "(rc-update del wazuh-agent 2>/dev/null || true); "
            "rm -f /etc/init.d/wazuh-agent"
        )

    # --- Package removal + orphan user/group cleanup ---
    # Recognized package managers run postrm/postun hooks that drop the wazuh
    # user/group, so we let them handle it. Arch and the no-package-manager
    # fallback are extraction-based, so they must remove the user/group by hand.
    manual_user_cleanup = (
        "userdel wazuh 2>/dev/null || true; groupdel wazuh 2>/dev/null || true"
    )
    if os_type == "arch":
        pkg_remove = ""
        cleanup_users = manual_user_cleanup
    elif pkg_mgr == "apt":
        pkg_remove = "apt-get remove -y wazuh-agent || true"
        cleanup_users = ""
    elif pkg_mgr in ("dnf", "yum"):
        pkg_remove = f"{pkg_mgr} remove -y wazuh-agent || true"
        cleanup_users = ""
    elif pkg_mgr == "zypper":
        pkg_remove = "zypper --non-interactive remove wazuh-agent || true"
        cleanup_users = ""
    else:
        # No recognized package manager: the install can only have been placed
        # by extraction, so tear it down by path like the Arch case.
        pkg_remove = ""
        cleanup_users = manual_user_cleanup

    # --- Preserve or wipe the enrollment key backup ---
    # Runs before pkg_remove/rm -rf so client.keys still exists to be copied.
    if wipe_keys:
        key_phase = f"rm -f '{_KEY_BACKUP}'"
    else:
        key_phase = (
            f"mkdir -p '{backup_dir}'; "
            f"cp '{_CLIENT_KEYS}' '{_KEY_BACKUP}' 2>/dev/null || true; "
            f"chown {os.getuid()}:{os.getgid()} '{_KEY_BACKUP}' 2>/dev/null || true"
        )

    return f"""
        {stop_cmd}
        {service_teardown}
        {key_phase}
        {pkg_remove}
        {cleanup_users}
        rm -rf '{LINUX_WAZUH_DIR}'
    """


def remove_agent(wipe_keys: bool = False):
    """Uninstall the Wazuh agent and clean up system resources.

    Removal is driven by the detected package manager and init system rather
    than a single hard-coded path, so it works across apt/dnf/yum/zypper and
    both systemd and non-systemd (OpenRC/SysV) hosts:

    * Package-managed installs (deb/rpm/zypper) are removed by the package
      manager, whose postrm/postun hooks drop the wazuh user and group.
    * Arch installs are bsdtar-extracted and tracked by no package manager, so
      they are always torn down by path with a manual user/group cleanup.
    * Hosts with no recognized package manager fall back to the same manual
      teardown as Arch (the install can only have been extraction-based).

    When ``wipe_keys=True`` (used on user logout) the persistent client.keys
    backup is also deleted so the next user starts with a clean enrollment.
    """
    if not agent_present(wipe_keys):
        return True

    script = build_remove_script(wipe_keys)
    success, output = run_privileged_command(["sh", "-c", script])
    if success:
        logger.info("Wazuh agent removed successfully")
    else:
        logger.error(f"Failed to remove Wazuh agent: {output}")
    return success

def full_install(progress_callback=None):
    pkg_path = download_package(progress_callback)
    if not pkg_path:
        if progress_callback: progress_callback("Download failed")
        return False
        
    agent_name = get_agent_name()
    agent_group = get_agent_group()

    os_type = _get_os_info()
    ossec_conf = f"{LINUX_WAZUH_DIR}/etc/ossec.conf"
    install_cmd = ""
    deploy_env = _deploy_env(agent_name, agent_group)
    if os_type == "deb":
        install_cmd = f"{deploy_env} dpkg -i '{pkg_path}'"
    elif os_type == "rpm":
        install_cmd = f"{deploy_env} rpm -ihv '{pkg_path}'"
    elif os_type == "arch":
        # No postinst runs when extracting with bsdtar — create the wazuh user/group, extract,
        # fix ownership, then stamp manager + group into ossec.conf manually
        install_cmd = (
            "(getent group wazuh >/dev/null || groupadd --system wazuh) && "
            "(getent passwd wazuh >/dev/null || useradd --system --no-create-home "
            "--home /var/ossec --shell /sbin/nologin -g wazuh wazuh) && "
            f"bsdtar -xpf '{pkg_path}' -C / && "
            "chown -R wazuh:wazuh /var/ossec && "
            f"sed -i \"s|<address>.*</address>|<address>{WAZUH_MANAGER}</address>|\" '{ossec_conf}' && "
            f"sed -i \"s|<groups>.*</groups>|<groups>{agent_group}</groups>|\" '{ossec_conf}'"
        )

    agent_auth = f"{LINUX_WAZUH_DIR}/bin/agent-auth"
    backup_dir = os.path.dirname(_KEY_BACKUP)

    # Always re-enroll so the manager receives the group on every install.
    # The key backup is still written for future repair/recovery flows.
    enrollment_script = f"""
            rm -f '{_CLIENT_KEYS}'
            '{agent_auth}' -m '{WAZUH_MANAGER}' -P '{WAZUH_REGISTRATION_PORT}' -A '{agent_name}' -G '{agent_group}'
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
