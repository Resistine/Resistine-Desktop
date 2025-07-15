"""
VPN Functions for WireGuard on Linux
-------------------------------------
This module contains functions for managing a WireGuard VPN on Linux.
The functions include checking if WireGuard is installed, generating keys,
creating a WireGuard configuration file, starting and stopping the VPN service,
and checking the status of the VPN service.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import sys
import os
import subprocess
import json
from python_wireguard import Key


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

def create_wireguard_config(private_key, public_key, client_ip_address, dns, allowed_ips, endpoint, port, config_path):
    """
    Create a WireGuard VPN configuration file.

    :param private_key: The private key for the WireGuard interface.
    :param public_key: The public key for the WireGuard peer.
    :param client_ip_address: The IP address of the client.
    :param dns: The DNS server to use.
    :param allowed_ips: The allowed IPs for the WireGuard peer.
    :param endpoint: The endpoint address of the WireGuard peer.
    :param port: The port number of the WireGuard peer.
    :param config_path: The path to save the configuration file.
    """
    config_template = f"""[Interface]
PrivateKey = {private_key}
Address = {client_ip_address}
DNS = {dns}

[Peer]
PublicKey = {public_key}
AllowedIPs = {allowed_ips}
Endpoint = {endpoint}:{port}
"""

    try:
        script_dir = os.path.dirname(__file__)
        config_file_path = os.path.join(script_dir, config_path)
        with open(config_file_path, "w") as config_file:
            config_file.write(config_template)
        print(f"Configuration file created at {config_file_path}")
    except Exception as e:
        print(f"Error writing configuration file: {e}")

def generate_keys():
    """
    Generate WireGuard private and public keys.

    :return: A dictionary containing the private and public keys.
    """
    try:
        private_key, public_key = Key.key_pair()

        keys = {
            "private_key": private_key,
            "public_key": public_key
        }
        script_dir = os.path.dirname(__file__)
        keys_path = os.path.join(script_dir, "keys.json")
        with open(keys_path, "w") as json_file:
            json.dump(keys, json_file, indent=4)

        print("Keys generated successfully.")
        print(f"Private Key: {private_key}")
        print(f"Public Key: {public_key}")
    except Exception as e:
        print(f"Error generating keys: {e}")

def check_service_status(interface_name, test_ip):
    """
    Check the status of the WireGuard VPN service.

    :param interface_name: The name of the WireGuard interface.
    :param test_ip: The IP address to ping for testing connectivity.
    :return: "Running" if the service is up, "Stopped" otherwise.
    """
    try:
        result = subprocess.run(['sudo', 'wg', 'show', interface_name], check=True, capture_output=True, text=True)
    except Exception as e:
        print(f"Error checking WireGuard interface {interface_name}: {e}")
        return "Stopped"

    try:
        result = subprocess.run(['ip', 'route'], check=True, capture_output=True, text=True)
    except Exception as e:
        print(f"Error retrieving routing table: {e}")
        return "Stopped"

    try:
        result = subprocess.run(['ping', '-c', '4', test_ip], check=True, capture_output=True, text=True)
    except Exception as e:
        print(f"Error pinging {test_ip}: {e}")
        return "Stopped"

    return "Running"

def check_wireguard_installed():
    """
    Check if WireGuard is installed on the system.

    :return: True if WireGuard is installed, False otherwise.
    """
    try:
        subprocess.run(['which', 'wg'], check=True, capture_output=True, text=True)
        print("WireGuard (wg) is installed.")
    except Exception:
        print("WireGuard (wg) is not installed.")
        return False

    try:
        subprocess.run(['which', 'wg-quick'], check=True, capture_output=True, text=True)
        print("WireGuard (wg-quick) is installed.")
    except Exception:
        print("WireGuard (wg-quick) is not installed.")
        return False
    return True

def stop_vpn(config_path):
    """
    Stop the WireGuard VPN service with a specified configuration.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service is stopped successfully, False otherwise.
    """
    try:
        interface_name = f'{config_path}'
        command = ['wg-quick', 'down', interface_name]
        output = subprocess.run(command, check=True)
        if output.returncode != 0:
            print("Failed to stop VPN service.")
            return False
        return True
    except Exception as e:
        print(f"Failed to stop VPN service: {e}")
        return False

def start_vpn(config_path):
    """
    Start the WireGuard VPN service with a specified configuration.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service is started successfully, False otherwise.
    """
    try:
        interface_name = f'{config_path}'
        command = ['wg-quick', 'up', interface_name]
        output = subprocess.run(command, check=True)
        if output.returncode != 0:
            print("Failed to start VPN service.")
            return False
        return True
    except Exception as e:
        print(f"Failed to start VPN service: {e}")
        return False
