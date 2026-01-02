"""
VPN Functions for WireGuard on Linux
-------------------------------------
This module contains functions for managing a WireGuard VPN on Linux.
The functions include checking if WireGuard is installed, generating keys,
creating a WireGuard configuration file, starting and stopping the VPN service,
and checking the status of the VPN service.
Author: Petr and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json
import os
import shutil
import subprocess
import sys

from gui.dialogs import CTkPasswordDialog
from utils.i18n import get_text
from utils.logger import logger

# Removed standard logging setup

# Keychain Constants
KEYS_FILE_PATH = os.path.expanduser("~/.config/resistine/keys.json")


def get_writable_wireguard_dir():
    """Get a writable directory for WireGuard configuration files"""
    from utils.settings import get_config_dir

    wireguard_dir = os.path.join(get_config_dir(), "wireguard")
    os.makedirs(wireguard_dir, exist_ok=True)
    return wireguard_dir


def is_admin():
    """
    Check if the script is running with root privileges.

    :return: True if running as root, False otherwise.
    """
    return os.geteuid() == 0


def run_privileged_command(command_args):
    """
    Run a command with elevated privileges using pkexec or sudo fallback.

    :param command_args: List of command arguments (e.g., ["wg", "show"])
    :return: subprocess.CompletedProcess or None if failed
    """
    # Try pkexec first (standard GUI way)
    if shutil.which("pkexec"):
        try:
            # Resolve absolute path for the command
            # pkexec often fails if the command is not in its minimal PATH (exit code 126)
            executable = shutil.which(command_args[0])
            full_command_args = (
                [executable] + command_args[1:] if executable else command_args
            )

            logger.info(f"Attempting to run with pkexec: {full_command_args}")
            # pkexec runs the command directly, handling the GUI prompt
            return subprocess.run(
                ["pkexec"] + full_command_args,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() or e.stdout.strip() or "No output"
            logger.warning(
                f"pkexec failed (code {e.returncode}): {error_msg}. Falling back to sudo."
            )
        except Exception as e:
            logger.warning(f"pkexec error: {e}. Falling back to sudo.")

    # Fallback to sudo with GUI password prompt
    logger.info("Falling back to sudo with themed password prompt")

    dialog = CTkPasswordDialog(
        title=get_text("dialog.password.title"),
        text=get_text("vpn.linux.privileges_required", command=command_args[0]),
    )
    password = dialog.get_input()

    if not password:
        logger.warning("User cancelled password prompt")
        return None

    try:
        # Run sudo with -S to read password from stdin
        return subprocess.run(
            ["sudo", "-S"] + command_args,
            input=password + "\n",
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"sudo failed: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"sudo error: {e}")
        return None


def run_as_admin(file_path):
    """
    Attempt to elevate the script to admin privileges on Linux.

    :param file_path: The path to the script file.
    :return: True if elevation is successful, False otherwise.
    """
    if is_admin():
        logger.info("Already running as root.")
        return True
    else:
        logger.info("Attempting to elevate to root...")
        result = run_privileged_command([sys.executable, file_path])
        if result and result.returncode == 0:
            logger.info("Elevation request accepted.")
            return True
        else:
            logger.info("Elevation request denied or failed.")
            return False


def run_installer_as_admin(file_path):
    """
    Run an installer file with admin privileges.

    :param file_path: The path to the installer file.
    :return: True if successful, False otherwise.
    """
    try:
        logger.info(f"Running installer as admin: {file_path}...")
        # Note: apt might be interactive, but for now we try basic install
        # Ideally we'd use a proper packagekit client, but this is a quick fix
        result = run_privileged_command(["apt", "install", "-y", "wireguard"])
        if result and result.returncode == 0:
            logger.info("WireGuard installation command executed.")
            return True
        else:
            logger.info("Failed to install WireGuard.")
            return False
    except Exception as e:
        logger.error(f"Error during installation: {e}")
        return False


def generate_wireguard_keys():
    """
    Generate WireGuard public/private key pair using wg command.

    Returns:
        dict: {
            'private_key': str,
            'public_key': str
        }
        None: If key generation fails
    """
    try:
        private_key = subprocess.check_output(["wg", "genkey"], text=True).strip()
        public_key = subprocess.check_output(
            ["wg", "pubkey"], input=private_key, text=True
        ).strip()

        return {
            "private_key": private_key,
            "public_key": public_key,
        }

    except subprocess.CalledProcessError as e:
        logger.error(f"Key generation command failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Key generation failed: {e}")
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
        os.chmod(KEYS_FILE_PATH, 0o600)
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


def parse_and_create_vpn_config(vpn_config_json_string, config_name="wg0"):
    """
    Parse VPN configuration from server response and create WireGuard config file.

    Args:
        vpn_config_json_string: JSON string containing VPN config from server
        config_name: Name for the config file (default: "wg0")

    Returns:
        str: Path to created config file, or None if failed
    """
    try:
        # Parse the VPN config JSON string
        vpn_config = json.loads(vpn_config_json_string)

        # Extract Peer configuration
        peer_config = vpn_config.get("Peer", {})
        server_public_key = peer_config.get("PublicKey", "")
        allowed_ips = peer_config.get("AllowedIPs", [])
        endpoint = peer_config.get("Endpoint", "")

        # Extract Interface configuration
        interface_config = vpn_config.get("Interface", {})
        client_address = interface_config.get("Address", "")
        dns_servers = interface_config.get("DNS", [])

        # Get private key from keychain (local function)
        private_key = get_wireguard_private_key()
        if not private_key:
            logger.error("Private key not found in keychain")
            return None

        # Convert AllowedIPs array to comma-separated string
        allowed_ips_str = (
            ", ".join(allowed_ips)
            if isinstance(allowed_ips, list)
            else str(allowed_ips)
        )

        # Convert DNS array to comma-separated string
        dns_str = (
            ", ".join(dns_servers)
            if isinstance(dns_servers, list)
            else str(dns_servers)
        )

        # Build WireGuard config content
        config_content = f"""[Interface]
PrivateKey = {private_key}
Address = {client_address}
DNS = {dns_str}

[Peer]
PublicKey = {server_public_key}
AllowedIPs = {allowed_ips_str}
Endpoint = {endpoint}
"""

        # Determine config path using the shared utility
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

        wireguard_dir = get_writable_wireguard_dir()

        # Create config file path
        config_filename = f"{config_name}.conf"
        config_path = os.path.join(wireguard_dir, config_filename)

        # Write config file
        with open(config_path, "w") as config_file:
            config_file.write(config_content)

        # Set strict permissions (600) to avoid "world accessible" warning
        os.chmod(config_path, 0o600)

        logger.info(f"WireGuard config created at: {config_path}")

        return config_path

    except json.JSONDecodeError as e:
        logger.error(f"Error parsing VPN config JSON: {e}")
        return None
    except KeyError as e:
        logger.error(f"Error: Missing required field in VPN config: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating VPN config: {e}")
        return None


def check_service_status(interface_name, test_ip):
    """
    Check the status of the WireGuard VPN service.

    :param interface_name: The name of the WireGuard interface.
    :param test_ip: The IP address to ping for testing connectivity.
    :return: "Running" if the service is up, "Stopped" otherwise.
    """
    try:
        # Check if interface exists
        result = run_privileged_command(["wg", "show", interface_name])

        if not result or result.returncode != 0:
            return "Stopped"

        # Optional: Check connectivity
        if test_ip:
            ping_result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", test_ip],
                check=False,
                capture_output=True,
                text=True,
            )
            if ping_result.returncode != 0:
                logger.warning(
                    f"Interface {interface_name} up but ping to {test_ip} failed."
                )

        return "Running"
    except Exception as e:
        logger.error(f"Error checking WireGuard interface {interface_name}: {e}")
        return "Stopped"


def check_wireguard_installed():
    """
    Check if WireGuard is installed on the system.

    :return: True if WireGuard is installed, False otherwise.
    """
    try:
        subprocess.run(["which", "wg"], check=True, capture_output=True, text=True)
    except Exception:
        return False

    try:
        subprocess.run(
            ["which", "wg-quick"], check=True, capture_output=True, text=True
        )
    except Exception:
        return False
    return True


def stop_vpn(config_path):
    """
    Stop the WireGuard VPN service with a specified configuration.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service is stopped successfully, False otherwise.
    """
    try:
        command = ["wg-quick", "down", config_path]
        result = run_privileged_command(command)
        if result and result.returncode == 0:
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to stop VPN service: {e}")
        return False


def start_vpn(config_path):
    """
    Start the WireGuard VPN service with a specified configuration.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service is started successfully, False otherwise.
    """
    try:
        command = ["wg-quick", "up", config_path]
        result = run_privileged_command(command)
        if result and result.returncode == 0:
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to start VPN service: {e}")
        return False


def setup_vpn_keys():
    """
    Generate and save new WireGuard keys for the session.
    Returns the public key if successful, None otherwise.
    """
    try:
        # Step 1: Regenerate fresh keys for this sign-in session
        logger.debug("Regenerating WireGuard keys for new login session")
        delete_wireguard_keys()

        # Generate new key pair
        keys = generate_wireguard_keys()
        if not keys:
            logger.error("Failed to generate keys")
            return None

        # Save both private and public keys
        if not save_wireguard_keys(keys["private_key"], keys["public_key"]):
            logger.error("Failed to save keys securely")
            return None

        # Get public key for API transmission
        public_key = keys["public_key"]

        if not public_key:
            logger.error("Failed to get public key")
            return None

        logger.debug(
            f"WireGuard Public Key Validated: Length={len(public_key)} characters"
        )
        return public_key

    except Exception as e:
        logger.error(f"Error setting up VPN keys: {e}")
        return None


def save_vpn_configuration(vpn_config_json):
    """
    Parse and save the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    try:
        if not vpn_config_json:
            return None

        logger.debug("WireGuard config received from API")

        # Log redacted config for debugging
        try:
            vpn_config = (
                json.loads(vpn_config_json)
                if isinstance(vpn_config_json, str)
                else vpn_config_json
            )
            safe_config = {}
            if "Interface" in vpn_config:
                safe_config["Interface"] = {
                    "Address": vpn_config["Interface"].get("Address", ""),
                    "DNS": vpn_config["Interface"].get("DNS", []),
                    "PrivateKey": (
                        "[REDACTED]"
                        if vpn_config["Interface"].get("PrivateKey")
                        else None
                    ),
                }
            if "Peer" in vpn_config:
                safe_config["Peer"] = {
                    "PublicKey": (
                        "[REDACTED]" if vpn_config["Peer"].get("PublicKey") else None
                    ),
                    "AllowedIPs": vpn_config["Peer"].get("AllowedIPs", []),
                    "Endpoint": vpn_config["Peer"].get("Endpoint", ""),
                }
            logger.debug(f"VPN Config (redacted): {json.dumps(safe_config)}")
        except Exception as e:
            logger.debug(f"Error parsing VPN config for logging: {e}")

        # Create config file
        config_path = parse_and_create_vpn_config(vpn_config_json, config_name="wg0")

        if config_path:
            logger.info("VPN configuration saved successfully")
            return config_path
        else:
            logger.warning("Failed to create VPN config")
            return None

    except Exception as e:
        logger.warning(f"Error creating VPN config: {e}")
        return None
