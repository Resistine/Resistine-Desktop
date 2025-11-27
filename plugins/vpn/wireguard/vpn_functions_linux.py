"""
VPN Functions for WireGuard on Linux
-------------------------------------
This module contains functions for managing a WireGuard VPN on Linux.
The functions include checking if WireGuard is installed, generating keys,
creating a WireGuard configuration file, starting and stopping the VPN service,
and checking the status of the VPN service.
Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import sys
import os
import subprocess
import json
import logging

# Set up logger
logger = logging.getLogger(__name__)

def is_admin():
    """
    Check if the script is running with root privileges.

    :return: True if running as root, False otherwise.
    """
    return os.geteuid() == 0

def run_as_admin(file_path):
    """
    Attempt to elevate the script to admin privileges on Linux.

    :param file_path: The path to the script file.
    :return: True if elevation is successful, False otherwise.
    """
    if is_admin():
        print("Already running as root.")
        return True
    else:
        print("Attempting to elevate to root...")
        try:
            subprocess.run(["sudo", sys.executable, file_path], check=True)
            print("Elevation request accepted.")
            return True
        except Exception as e:
            print(f"Elevation request denied or failed: {e}")
            return False

def run_installer_as_admin(file_path):
    """
    Run an installer file with admin privileges.

    :param file_path: The path to the installer file.
    """
    try:
        print(f"Running installer as admin: {file_path}...")
        subprocess.run(["sudo", "apt", "install", "wireguard"], check=True)
        print("WireGuard installation command executed.")
    except Exception as e:
        print(f"Error during installation: {e}")
        
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
        private_key = subprocess.check_output(['wg', 'genkey'], text=True).strip()
        public_key = subprocess.check_output(['wg', 'pubkey'], input=private_key, text=True).strip()
        
        return {
            'private_key': private_key,
            'public_key': public_key,
        }
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Key generation command failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Key generation failed: {e}")
        return None

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
        
        # Get private key from keychain
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        from utils.keychain_linux import get_wireguard_private_key
        
        private_key = get_wireguard_private_key()
        if not private_key:
            logger.error("Private key not found in keychain")
            return None
        
        # Convert AllowedIPs array to comma-separated string
        allowed_ips_str = ", ".join(allowed_ips) if isinstance(allowed_ips, list) else str(allowed_ips)
        
        # Convert DNS array to comma-separated string
        dns_str = ", ".join(dns_servers) if isinstance(dns_servers, list) else str(dns_servers)
        
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
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        from utils.functions import get_writable_wireguard_dir
        
        wireguard_dir = get_writable_wireguard_dir()
        
        # Create config file path
        config_filename = f"{config_name}.conf"
        config_path = os.path.join(wireguard_dir, config_filename)
        
        # Write config file
        with open(config_path, "w") as config_file:
            config_file.write(config_content)
        
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
        result = subprocess.run(['sudo', 'wg', 'show', interface_name], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            return "Stopped"
            
        # Optional: Check connectivity
        if test_ip:
            ping_result = subprocess.run(['ping', '-c', '1', '-W', '1', test_ip], check=False, capture_output=True, text=True)
            if ping_result.returncode != 0:
                 logger.warning(f"Interface {interface_name} up but ping to {test_ip} failed.")
                 
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
        subprocess.run(['which', 'wg'], check=True, capture_output=True, text=True)
        # print("WireGuard (wg) is installed.")
    except Exception:
        # print("WireGuard (wg) is not installed.")
        return False

    try:
        subprocess.run(['which', 'wg-quick'], check=True, capture_output=True, text=True)
        # print("WireGuard (wg-quick) is installed.")
    except Exception:
        # print("WireGuard (wg-quick) is not installed.")
        return False
    return True

def stop_vpn(config_path):
    """
    Stop the WireGuard VPN service with a specified configuration.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service is stopped successfully, False otherwise.
    """
    try:
        # If config_path is a full path, wg-quick might need just the conf file or the interface name
        # Usually wg-quick up /path/to/conf works.
        command = ['sudo', 'wg-quick', 'down', config_path]
        output = subprocess.run(command, check=True)
        return True
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
        command = ['sudo', 'wg-quick', 'up', config_path]
        output = subprocess.run(command, check=True)
        return True
    except Exception as e:
        logger.error(f"Failed to start VPN service: {e}")
        return False
