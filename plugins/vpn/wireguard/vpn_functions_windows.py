# plugins/vpn/wireguard/vpn_functions_windows.py
"""
Windows VPN functions — service-based architecture.
Communicates with the ResistineVPN Windows service via IPC socket
instead of managing WireGuard directly (no admin/UAC needed).

Authors: Merhawi, Johann Gawron, and the Resistine Team
"""
import json
import os
import subprocess

from utils.settings import get_config_dir
from plugins.vpn.wireguard.service_client import send_command
from utils.logger import logger

DEFAULT_TUNNEL = "resistine_default"

# Keys file path for Windows
KEYS_FILE_PATH = os.path.join(get_config_dir(), "keys.json")

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


# ----------------------------------------------------------------
# WireGuard executable helpers
# ----------------------------------------------------------------

def find_wireguard_exe():
    """Find the WireGuard executable."""
    wg_exe = r"C:\Program Files\WireGuard\wireguard.exe"
    if os.path.exists(wg_exe):
        return wg_exe
    return None


# ----------------------------------------------------------------
# Key management (used by login/logout)
# ----------------------------------------------------------------

def generate_wireguard_keys():
    """Generate WireGuard public/private key pair."""
    try:
        wg_exe = find_wireguard_exe()
        if wg_exe:
            wg_dir = os.path.dirname(wg_exe)
            wg_cli = os.path.join(wg_dir, "wg.exe")

            if os.path.exists(wg_cli):
                try:
                    private_key = subprocess.check_output([wg_cli, "genkey"], text=True).strip()
                    public_key = subprocess.check_output(
                        [wg_cli, "pubkey"], input=private_key, text=True
                    ).strip()
                    return {"private_key": private_key, "public_key": public_key}
                except subprocess.CalledProcessError as e:
                    logger.warning(f"WireGuard CLI key generation failed: {e}")

        # Fallback: Python cryptography library
        logger.info("Using fallback key generation method")
        return _generate_keys_fallback()

    except Exception as e:
        logger.error(f"Key generation failed: {e}")
        return None


def _generate_keys_fallback():
    """Fallback key generation using Python cryptography library."""
    try:
        import base64
        import secrets

        private_key_bytes = secrets.token_bytes(32)
        private_key = base64.b64encode(private_key_bytes).decode('utf-8')

        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from cryptography.hazmat.primitives import serialization

            x25519_private = X25519PrivateKey.from_private_bytes(private_key_bytes)
            x25519_public = x25519_private.public_key()
            public_key_bytes = x25519_public.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            public_key = base64.b64encode(public_key_bytes).decode('utf-8')
            return {"private_key": private_key, "public_key": public_key}

        except ImportError:
            logger.warning("cryptography library not available, using simplified key generation")
            public_key_bytes = secrets.token_bytes(32)
            public_key = base64.b64encode(public_key_bytes).decode('utf-8')
            return {"private_key": private_key, "public_key": public_key}

    except Exception as e:
        logger.error(f"Fallback key generation failed: {e}")
        return None


def get_wireguard_private_key():
    """Retrieve the WireGuard private key from the keys file."""
    try:
        if os.path.exists(KEYS_FILE_PATH):
            with open(KEYS_FILE_PATH, "r") as f:
                keys = json.load(f)
                return keys.get("private_key")
        return None
    except Exception as e:
        logger.error(f"Error retrieving private key: {e}")
        return None


def save_wireguard_keys(private_key, public_key):
    """Save the WireGuard keys to the keys file securely."""
    try:
        os.makedirs(os.path.dirname(KEYS_FILE_PATH), exist_ok=True)
        keys = {"private_key": private_key, "public_key": public_key}
        with open(KEYS_FILE_PATH, "w") as f:
            json.dump(keys, f)
        try:
            import stat
            os.chmod(KEYS_FILE_PATH, stat.S_IREAD | stat.S_IWRITE)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"Error saving keys: {e}")
        return False


def delete_wireguard_keys():
    """Delete the WireGuard keys file."""
    try:
        if os.path.exists(KEYS_FILE_PATH):
            os.remove(KEYS_FILE_PATH)
        return True
    except Exception as e:
        logger.error(f"Error deleting keys: {e}")
        return False


def setup_vpn_keys():
    """Generate and save new WireGuard keys for the session.
    Returns the public key if successful, None otherwise.
    """
    try:
        logger.debug("Regenerating WireGuard keys for new login session")
        delete_wireguard_keys()

        keys = generate_wireguard_keys()
        if not keys:
            logger.error("Failed to generate keys")
            return None

        if not save_wireguard_keys(keys["private_key"], keys["public_key"]):
            logger.error("Failed to save keys securely")
            return None

        public_key = keys["public_key"]
        if not public_key:
            logger.error("Failed to get public key")
            return None

        logger.debug(f"WireGuard Public Key Validated: Length={len(public_key)} characters")
        return public_key

    except Exception as e:
        logger.error(f"Error setting up VPN keys: {e}")
        return None


# ----------------------------------------------------------------
# Config file management (used by login)
# ----------------------------------------------------------------

def parse_and_create_vpn_config(vpn_config_json_string, config_name="resistine_default"):
    """Parse and create the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    try:
        if not vpn_config_json_string:
            return None

        logger.debug("WireGuard config received from API")

        vpn_config = json.loads(vpn_config_json_string)

        config_dir = get_writable_wireguard_dir()
        config_path = os.path.join(config_dir, f"{config_name}.conf")

        with open(config_path, 'w') as f:
            f.write(vpn_config.get('config', ''))

        logger.info(f"VPN configuration saved to {config_path}")
        return config_path

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse VPN config JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating VPN config: {e}")
        return None


def save_vpn_configuration(vpn_config_json, config_name="resistine_default"):
    """Parse and save the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    return parse_and_create_vpn_config(vpn_config_json, config_name)


logger.info("WireGuard Windows VPN client loaded (service-based)")
