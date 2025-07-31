"""
VPN Functions for WireGuard on Darwin
-------------------------------------
This module contains functions for managing a WireGuard VPN on Darwin.
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



def is_admin():
    """
    Check if the script is running with root privileges.

    :return: True if running as root, False otherwise.
    """
    return os.geteuid() == 0

def run_as_admin(file_path): 
    """
    Attempt to elevate the script to admin privileges on Darwin.

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
        if subprocess.run(["which", "brew"], capture_output=True, text=True).returncode != 0:
            
            raise EnvironmentError("Homebrew not found. Install it from https://brew.sh")

        subprocess.run(["brew", "install", "wireguard-tools"], check=True)
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
    Generate WireGuard private and public keys using command line tools.
    """
    try:
        private_key_result = subprocess.run(['wg', 'genkey'], capture_output=True, text=True, check=True)
        private_key = private_key_result.stdout.strip()

        public_key_result = subprocess.run(['wg', 'pubkey'], input=private_key, capture_output=True, text=True, check=True)
        public_key = public_key_result.stdout.strip()

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
        return keys
    except Exception as e:
        print(f"Error generating keys: {e}")
        return None
def check_service_status(interface_name, test_ip):
    """
    Check the status of the WireGuard VPN service.
    """
    try:
        # Get all WireGuard interfaces
        result = subprocess.run(['sudo', 'wg', 'show'], capture_output=True, text=True, check=True)
        
        # Check if any interface is running (don't look for specific interface name)
        if result.stdout.strip():
            print(f"Found active WireGuard interfaces")
            
            # Check if we can ping the test IP
            try:
                ping_result = subprocess.run(['ping', '-c', '1', '-t', '2', test_ip], 
                                           capture_output=True, text=True, timeout=5)
                if ping_result.returncode == 0:
                    print(f"Successfully pinged {test_ip}")
                    return "Running"
                else:
                    print(f"Failed to ping {test_ip}")
                    return "Stopped"
            except Exception as e:
                print(f"Error pinging {test_ip}: {e}")
                return "Stopped"
        else:
            print("No active WireGuard interfaces found")
            return "Stopped"
            
    except subprocess.CalledProcessError as e:
        print(f"Error running wg show: {e}")
        return "Stopped"
    except Exception as e:
        print(f"Error checking WireGuard status: {e}")
        return "Stopped"

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

def start_vpn(config_path):
    """Start the WireGuard VPN service with a specified configuration."""
    try:
        # Use the config file directly with wg-quick
        command = ['sudo', 'wg-quick', 'up', config_path]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print(f"VPN started successfully: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to start VPN: {e.stderr}")
        return False
    
def stop_vpn(config_path):
    """Stop the WireGuard VPN service with a specified configuration."""
    try:
        # Extract interface name from config file
        interface_name = os.path.basename(config_path).replace('.conf', '')
        
        # Try to stop using wg-quick down with the full config path
        try:
            command = ['sudo', 'wg-quick', 'down', config_path]  # Use full path instead of just interface name
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            print(f"VPN stopped successfully: {result.stdout}")
            return True
        except subprocess.CalledProcessError:
            # If wg-quick down fails, try to stop manually
            print(f"wg-quick down failed, trying manual stop for {interface_name}")
            
            # Find the actual interface name (might be utunX)
            try:
                result = subprocess.run(['sudo', 'wg', 'show'], capture_output=True, text=True, check=True)
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'interface:' in line and 'utun' in line:
                        # Extract the actual interface name
                        actual_interface = line.split(':')[1].strip()
                        print(f"Found actual interface: {actual_interface}")
                        
                        # Stop the actual interface
                        command = ['sudo', 'ifconfig', actual_interface, 'down']
                        subprocess.run(command, capture_output=True, text=True, check=True)
                        
                        print(f"VPN stopped successfully using manual method")
                        return True
            except Exception as e:
                print(f"Manual stop failed: {e}")
                
        return False
    except Exception as e:
        print(f"Failed to stop VPN: {e}")
        return False



