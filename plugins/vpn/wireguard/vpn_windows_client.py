"""
Windows VPN client — thin IPC wrapper over the ResistineVPN service.
All tunnel control on Windows goes through here.

Authors: Merhawi
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from plugins.vpn.wireguard.service_client import send_command
from utils.logger import logger


def get_status(tunnel: str) -> dict:
    """Get current VPN status from the service."""
    try:
        result = send_command("status", tunnel)
        logger.info(f"VPN status for '{tunnel}': {result.get('state', 'Unknown')}")
        return result
    except Exception as e:
        logger.exception(f"Failed to get VPN status for tunnel '{tunnel}'")
        return {"status": "error", "state": "Stopped", "message": str(e)}


def connect(tunnel: str) -> dict:
    """Ask the service to connect the given tunnel."""
    try:
        logger.info(f"Requesting VPN connect for tunnel: {tunnel}")
        result = send_command("connect", tunnel)
        print(f"VPN connect result for '{tunnel}': {result}")
        state = result.get("state", "")
        if result.get("status") == "ok" or state in ("Running", "Starting"):
            logger.info(f"VPN connect accepted for '{tunnel}': {state or 'ok'}")
        else:
            logger.warning(f"VPN connect failed for '{tunnel}': {result.get('message', '')}")
        return result
    except Exception as e:
        logger.exception(f"Failed to connect VPN tunnel '{tunnel}'")
        return {"status": "error", "message": str(e)}


def disconnect(tunnel: str) -> dict:
    """Ask the service to disconnect the given tunnel."""
    try:
        logger.info(f"Requesting VPN disconnect for tunnel: {tunnel}")
        result = send_command("disconnect", tunnel)
        if result.get("status") == "ok":
            logger.info(f"VPN disconnected successfully: {tunnel}")
        else:
            logger.warning(f"VPN disconnect failed for '{tunnel}': {result.get('message', '')}")
        return result
    except Exception as e:
        logger.exception(f"Failed to disconnect VPN tunnel '{tunnel}'")
        return {"status": "error", "message": str(e)}


def toggle(tunnel: str) -> dict:
    """Toggle VPN state for the given tunnel."""
    status = get_status(tunnel)
    if status.get("state") == "Running":
        logger.info(f"Toggle: VPN is running, disconnecting '{tunnel}'")
        return disconnect(tunnel)
    else:
        logger.info(f"Toggle: VPN is stopped, connecting '{tunnel}'")
        return connect(tunnel)


logger.info("VPN Windows client loaded")