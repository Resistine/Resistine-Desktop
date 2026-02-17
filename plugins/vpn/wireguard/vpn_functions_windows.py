# plugins/vpn/wireguard/vpn_functions_windows.py
"""
Windows VPN functions — service-based architecture.
Communicates with the ResistineVPN Windows service via IPC socket
instead of managing WireGuard directly (no admin/UAC needed).

Authors: Merhawi, Johann Gawron, and the Resistine Team
"""
import os

from utils.settings import get_config_dir
from plugins.vpn.wireguard.service_client import send_command
from utils.logger import logger

DEFAULT_TUNNEL = "resistine_vpn"

# ----------------------------------------------------------------
# Directory / path helpers (needed by main.py at module level)
# ----------------------------------------------------------------

def get_writable_wireguard_dir():
    wg_dir = os.path.join(get_config_dir(), "wireguard")
    os.makedirs(wg_dir, exist_ok=True)
    return wg_dir


def get_config_path(tunnel_name):
    return os.path.join(get_writable_wireguard_dir(), f"{tunnel_name}.conf")


def check_wireguard_installed():
    """Check if WireGuard is installed (exe exists)."""
    wg_exe = r"C:\Program Files\WireGuard\wireguard.exe"
    return os.path.exists(wg_exe)


# ----------------------------------------------------------------
# Service-based VPN control
# ----------------------------------------------------------------

def get_status(tunnel=None):
    """Get VPN status from the Windows service."""
    tunnel = tunnel or DEFAULT_TUNNEL
    try:
        return send_command("status", tunnel)
    except Exception as e:
        logger.exception("Failed to get VPN status")
        return {"status": "error", "state": "Stopped", "message": str(e)}


def connect(tunnel=None):
    """Ask the service to start VPN."""
    tunnel = tunnel or DEFAULT_TUNNEL
    try:
        logger.info(f"Requesting VPN connect via service for tunnel: {tunnel}")
        return send_command("connect", tunnel)
    except Exception as e:
        logger.exception("Failed to connect VPN")
        return {"status": "error", "message": str(e)}


def disconnect(tunnel=None):
    """Ask the service to stop VPN."""
    tunnel = tunnel or DEFAULT_TUNNEL
    try:
        logger.info(f"Requesting VPN disconnect via service for tunnel: {tunnel}")
        return send_command("disconnect", tunnel)
    except Exception as e:
        logger.exception("Failed to disconnect VPN")
        return {"status": "error", "message": str(e)}


def toggle(tunnel=None):
    """Toggle VPN state (UI-safe, no admin needed)."""
    status = get_status(tunnel)
    if status.get("state") == "Running":
        return disconnect(tunnel)
    return connect(tunnel)


# ----------------------------------------------------------------
# Compatibility wrappers (used by main.py)
# ----------------------------------------------------------------

def start_vpn(tunnel_name):
    """Start VPN via service. Returns True on success."""
    result = connect(tunnel_name)
    return result.get("status") == "ok"


def stop_vpn(tunnel_name):
    """Stop VPN via service. Returns True on success."""
    result = disconnect(tunnel_name)
    return result.get("status") == "ok"


def check_service_status(tunnel_name, test_ip=None):
    """Check VPN status. Returns a string like 'Running' or 'Stopped'."""
    try:
        result = get_status(tunnel_name)
        return result.get("state", "Stopped")
    except Exception:
        return "Stopped"


logger.info("WireGuard Windows VPN client loaded (service-based)")
