"""
Windows VPN helper functions — key management, config management,
WireGuard installation checks, and service status wrappers.

This module does NOT manage tunnel connect/disconnect directly.
Use vpn_windows_client.py for all tunnel control.

Authors: Merhawi, Johann Gawron, and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json
import os
import subprocess

from utils.settings import get_config_dir
from utils.logger import logger

# Import client functions so main.py can use check_service_status etc.
# without importing from two places
from plugins.vpn.wireguard.vpn_windows_client import get_status, connect, disconnect, toggle


# ----------------------------------------------------------------
# Directory / path helpers
# ----------------------------------------------------------------

def get_writable_wireguard_dir() -> str:
    """Return (and create) the WireGuard config directory."""
    wg_dir = os.path.join(get_config_dir(), "wireguard")
    os.makedirs(wg_dir, exist_ok=True)
    return wg_dir


def get_config_path(tunnel_name: str) -> str:
    """Return the full path to a tunnel's .conf file."""
    return os.path.join(get_writable_wireguard_dir(), f"{tunnel_name}.conf")


# ----------------------------------------------------------------
# WireGuard installation checks
# ----------------------------------------------------------------

def find_wireguard_exe() -> str | None:
    """Find the WireGuard executable. Returns path or None."""
    candidates = [
        r"C:\Program Files\WireGuard\wireguard.exe",
        r"C:\Program Files (x86)\WireGuard\wireguard.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def find_wg_cli() -> str | None:
    """Find the wg.exe CLI tool. Returns path or None."""
    exe = find_wireguard_exe()
    if exe:
        cli = os.path.join(os.path.dirname(exe), "wg.exe")
        if os.path.exists(cli):
            return cli
    return None


def check_wireguard_installed() -> bool:
    """Return True if WireGuard is installed."""
    return find_wireguard_exe() is not None


# ----------------------------------------------------------------
# Service status wrappers (compatibility with main.py)
# ----------------------------------------------------------------

def start_vpn(tunnel_name: str) -> bool:
    """Connect tunnel via service. Returns True on success."""
    result = connect(tunnel_name)
    return result.get("status") == "ok"


def stop_vpn(tunnel_name: str) -> bool:
    """Disconnect tunnel via service. Returns True on success."""
    result = disconnect(tunnel_name)
    return result.get("status") == "ok"


def check_service_status(tunnel_name: str, test_ip: str = None) -> str:
    """Return a status string: 'Running', 'Stopped', etc.
    
    Args:
        tunnel_name: The tunnel to check.
        test_ip: Ignored on Windows (kept for cross-platform compat).
    """
    if not tunnel_name:
        return "Stopped"
    try:
        result = get_status(tunnel_name)
        return result.get("state", "Stopped")
    except Exception:
        return "Stopped"


# ----------------------------------------------------------------
# Key management
# ----------------------------------------------------------------

KEYS_FILE_PATH = os.path.join(get_config_dir(), "keys.json")


def generate_wireguard_keys() -> dict | None:
    """Generate a WireGuard public/private key pair.
    
    Tries wg.exe first, falls back to Python cryptography library.
    Returns dict with 'private_key' and 'public_key', or None on failure.
    """
    wg_cli = find_wg_cli()
    if wg_cli:
        try:
            private_key = subprocess.check_output(
                [wg_cli, "genkey"], text=True
            ).strip()
            public_key = subprocess.check_output(
                [wg_cli, "pubkey"], input=private_key, text=True
            ).strip()
            logger.info("WireGuard keys generated via wg.exe")
            return {"private_key": private_key, "public_key": public_key}
        except subprocess.CalledProcessError as e:
            logger.warning(f"wg.exe key generation failed: {e}")

    logger.info("Falling back to Python key generation")
    return _generate_keys_fallback()


def _generate_keys_fallback() -> dict | None:
    """Fallback key generation using the cryptography library."""
    try:
        import base64
        import secrets

        private_key_bytes = secrets.token_bytes(32)
        private_key = base64.b64encode(private_key_bytes).decode()

        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from cryptography.hazmat.primitives import serialization

            x25519_private = X25519PrivateKey.from_private_bytes(private_key_bytes)
            public_key_bytes = x25519_private.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            public_key = base64.b64encode(public_key_bytes).decode()
            logger.info("WireGuard keys generated via cryptography library")
            return {"private_key": private_key, "public_key": public_key}

        except ImportError:
            logger.warning("cryptography library not available, using random bytes for public key")
            public_key = base64.b64encode(secrets.token_bytes(32)).decode()
            return {"private_key": private_key, "public_key": public_key}

    except Exception as e:
        logger.error(f"Fallback key generation failed: {e}")
        return None


def get_wireguard_private_key() -> str | None:
    """Retrieve the saved WireGuard private key."""
    try:
        if os.path.exists(KEYS_FILE_PATH):
            with open(KEYS_FILE_PATH, "r") as f:
                return json.load(f).get("private_key")
        return None
    except Exception as e:
        logger.error(f"Error retrieving private key: {e}")
        return None


def save_wireguard_keys(private_key: str, public_key: str) -> bool:
    """Save WireGuard keys to disk."""
    try:
        os.makedirs(os.path.dirname(KEYS_FILE_PATH), exist_ok=True)
        with open(KEYS_FILE_PATH, "w") as f:
            json.dump({"private_key": private_key, "public_key": public_key}, f)
        try:
            import stat
            os.chmod(KEYS_FILE_PATH, stat.S_IREAD | stat.S_IWRITE)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"Error saving keys: {e}")
        return False


def delete_wireguard_keys() -> bool:
    """Delete the saved WireGuard keys file."""
    try:
        if os.path.exists(KEYS_FILE_PATH):
            os.remove(KEYS_FILE_PATH)
        return True
    except Exception as e:
        logger.error(f"Error deleting keys: {e}")
        return False


def setup_vpn_keys() -> str | None:
    """Generate and save new WireGuard keys.
    
    Returns the public key string on success, None on failure.
    """
    try:
        logger.debug("Regenerating WireGuard keys for new login session")
        delete_wireguard_keys()

        keys = generate_wireguard_keys()
        if not keys:
            logger.error("Failed to generate WireGuard keys")
            return None

        if not save_wireguard_keys(keys["private_key"], keys["public_key"]):
            logger.error("Failed to save WireGuard keys")
            return None

        public_key = keys["public_key"]
        logger.debug(f"WireGuard public key ready: length={len(public_key)}")
        return public_key

    except Exception as e:
        logger.error(f"Error setting up VPN keys: {e}")
        return None


# ----------------------------------------------------------------
# Config file management
# ----------------------------------------------------------------
def parse_and_create_vpn_config(
    vpn_config_json_string: str,
    config_name: str = "resistine_default",
) -> str | None:
    try:
        if not vpn_config_json_string:
            raise ValueError("Empty API response")

        vpn_config = json.loads(vpn_config_json_string)

        interface = vpn_config.get("Interface")
        peer = vpn_config.get("Peer")

        if not isinstance(interface, dict) or not isinstance(peer, dict):
            raise ValueError(f"Invalid WireGuard JSON shape: keys={list(vpn_config.keys())}")

        # Build WireGuard .conf text
        lines = []
        lines.append("[Interface]")
        for k, v in interface.items():
            if v is None:
                continue
            lines.append(f"{k} = {v}")

        lines.append("")  # blank line between sections
        lines.append("[Peer]")
        for k, v in peer.items():
            if v is None:
                continue
            lines.append(f"{k} = {v}")

        conf_text = "\n".join(lines).strip() + "\n"

        if not conf_text.strip():
            raise ValueError("Generated WireGuard config is empty")

        config_dir = get_writable_wireguard_dir()
        os.makedirs(config_dir, exist_ok=True)

        config_path = os.path.join(config_dir, f"{config_name}.conf")

        with open(config_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(conf_text)
            f.flush()
            os.fsync(f.fileno())

        logger.info(f"VPN configuration saved to: {os.path.abspath(config_path)}")
        return config_path

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse VPN config JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating VPN config: {e}")
        return None

def save_vpn_configuration(
    vpn_config_json: str,
    config_name: str = "resistine_default",
) -> str | None:
    """Alias for parse_and_create_vpn_config."""
    return parse_and_create_vpn_config(vpn_config_json, config_name)
