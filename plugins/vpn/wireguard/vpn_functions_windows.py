"""
VPN Functions for WireGuard on Windows
Author: Sherwin
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import ctypes
import sys
import os
import subprocess
import requests
import json
import time

def is_admin():
    """
    Check if the script is running with root privileges.

    :return: True if running as root, False otherwise.
    """
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin(file_path):
    """
    Attempt to elevate the script to admin privileges.

    :param file_path: The path to the file to be executed as admin.
    :return: True if elevation was successful, False otherwise.
    """
    if is_admin():
        print("Already running as admin.")
        return True
    else:
        print("Attempting to elevate to admin...")
        hinstance = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, file_path, None, 1)
        if hinstance <= 32:
            print("Elevation request denied or failed.")
            return False
        else:
            print("Elevation request accepted.")
            return True

def download_file(url, save_path):
    """
    Download a file from a URL and save it to a specified path.

    :param url: The URL of the file to download.
    :param save_path: The path where the downloaded file will be saved.
    :return: True if the download was successful, False otherwise.
    """
    try:
        print(f"Downloading {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(save_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"File downloaded: {save_path}")
    except requests.RequestException as e:
        print(f"Error downloading file: {e}")
        return False
    return True

def run_installer_as_admin(file_path):
    """
    Run an installer file with admin privileges.

    :param file_path: The path to the installer file.
    """
    try:
        print(f"Running installer as admin: {file_path}...")
        output = subprocess.run([file_path, "/S"], capture_output=True, text=True, check=True)
        print("Installation command executed.")
        if output.returncode != 0:
            try:
                print("Trying to uninstall services")
                subprocess.run(["C:\\Program Files\\WireGuard\\wireguard.exe", "/uninstallmanagerservice"], check=True)
                print("Services off")
            except subprocess.CalledProcessError as e:
                print(f"Failed to turn off services: {e}")
        else:
            print("Failed installation, try again")
    except subprocess.CalledProcessError as e:
        print(f"Error during installation: {e}")

def create_wireguard_config(private_key, public_key, client_ip_address, allowedips, endpoint, config_path):
    """
    Create a WireGuard VPN configuration file.

    :param private_key: The private key for the WireGuard interface.
    :param public_key: The public key of the peer.
    :param client_ip_address: The IP address of the client.
    :param allowedips: The allowed IPs for the peer.
    :param endpoint: The endpoint for the peer.
    :param config_path: The path where the configuration file will be saved.
    """
    config_template = f"""[Interface]
PrivateKey = {private_key}
Address = {client_ip_address}

[Peer]
PublicKey = {public_key}
AllowedIPs = {allowedips}
Endpoint = {endpoint}
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
    Generate WireGuard private and public keys on Windows.

    :return: A dictionary containing the private and public keys.
    """
    try:
        private_key = subprocess.check_output(["C:\\Program Files\\WireGuard\\wg.exe", "genkey"]).decode("utf-8").strip()
        public_key = subprocess.check_output(
            ["C:\\Program Files\\WireGuard\\wg.exe", "pubkey"], input=private_key.encode("utf-8")
        ).decode("utf-8").strip()

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

def check_service_status(tunnel_name, test_ip=None):
    """
    Check the status of the WireGuard service.

    :param tunnel_name: The name of the WireGuard tunnel.
    :param test_ip: An optional IP address to ping for additional verification.
    :return: The status of the service ('Running' or 'Stopped').
    """
    try:
        service_name = f"WireGuardTunnel${tunnel_name}"
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            check=True
        )
        content = result.stdout

        if "RUNNING" in content:
            if test_ip:
                try:
                    ping_result = subprocess.run(['ping', '-n', '2', test_ip], check=True, capture_output=True, text=True)
                    print(f"Ping to {test_ip} successful:\n{ping_result.stdout}")
                    return "Running"
                except Exception as e:
                    print(f"Error pinging {test_ip}: {e}")
                    return "Stopped"
            return "Running"
        elif "STOPPED" in content:
            return "Stopped"
        else:
            return "Stopped"
    except Exception as e:
        print(f"Error checking service status: {e}")
        return e

def check_wireguard_installed():
    """
    Validate if WireGuard is installed.
    :return: True if WireGuard is installed, False otherwise.
    """
    try:
        result = subprocess.run(
            ['wg.exe', '--version'],
            capture_output=True,
            text=True,
            check=True
        )
        print("WireGuard is installed.")
        return True
    except FileNotFoundError:
        print("WireGuard is not installed or 'wg.exe' is not in the system's PATH.")
        return False
    except subprocess.CalledProcessError as e:
        print(f"'wg.exe' returned an error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error checking WireGuard: {e}")
        return False

def install_tunnel(config_path):
    """
    Install the WireGuard VPN tunnel service.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service was installed successfully, False otherwise.
    """
    service_name = f"{os.path.basename(config_path).split('.')[0]}"

    try:
        interface_status = check_wireguard_interface(service_name)
        if interface_status:
            print(f"VPN service Tunnel {service_name} already installed.")
            return True
        else:
            print("Installing VPN Tunnel service...")
            command_install = f'"C:\\Program Files\\WireGuard\\wireguard.exe" /installtunnelservice "{config_path}"'
            output = subprocess.run(command_install, check=True, shell=True)
            if output.returncode != 0:
                print("Failed to install VPN service.")
                return False
            return True
    except Exception as e:
        print(f"Failed to install or activate VPN service: {e}")
        return False

def uninstall_tunnel(config_path):
    """
    Uninstall the WireGuard VPN tunnel service.

    :param config_path: The path to the WireGuard configuration file.
    :return: True if the service was uninstalled successfully, False otherwise.
    """
    service_name = f"{os.path.basename(config_path).split('.')[0]}"

    try:
        interface_status = check_wireguard_interface(service_name)
        if not interface_status:
            print(f"VPN service Tunnel {service_name} already uninstalled.")
            return True
        else:
            print("Uninstalling VPN Tunnel service...")
            command_install = f'"C:\\Program Files\\WireGuard\\wireguard.exe" /uninstalltunnelservice "{config_path}"'
            output = subprocess.run(command_install, check=True, shell=True)
            if output.returncode != 0:
                print("Failed to uninstall VPN service.")
                return False
            return True
    except Exception as e:
        print(f"Failed to uninstall VPN service: {e}")
        return False

def check_wireguard_interface(tunnel_name):
    """
    Check if the WireGuard tunnel interface is already installed.

    :param tunnel_name: The name of the WireGuard tunnel.
    :return: True if the tunnel exists, False otherwise.
    """
    service_name = f"WireGuardTunnel${tunnel_name}"
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            check=True
        )
        if "STATE" in result.stdout:
            print(f"Tunnel '{tunnel_name}' exists.")
            return True
    except subprocess.CalledProcessError:
        print(f"Tunnel '{tunnel_name}' does not exist.")
        return False


def stop_vpn(config_path, timeout=5, check_interval=1):
    """
    Stops the WireGuard VPN service and waits until it is fully stopped.
    Args:
        config_path (str): The path to the WireGuard configuration file.
        timeout (int): Maximum time to wait for the service to stop, in seconds.
        check_interval (int): Time to wait between status checks, in seconds.
    Returns:
        bool: True if the service was stopped successfully, False otherwise.
    """
    service_name = f"WireGuardTunnel${os.path.basename(config_path).split('.')[0]}"
    tunnel_name = f"{os.path.basename(config_path).split('.')[0]}"
    try:
        # Issue the stop command
        subprocess.run(['sc', 'stop', service_name], check=True)

        # Wait for the service to stop
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = check_service_status(tunnel_name)
            if status == 'Stopped':
                print(f"Service {service_name} has stopped.")
                return True
            time.sleep(check_interval)
        print(f"Timeout: Service {service_name} did not stop within {timeout} seconds.")
    except Exception as e:
        print(f"Failed to stop VPN service: {e}")
    return False

def start_vpn(config_path, timeout=5, check_interval=1):
    """
    Starts the WireGuard VPN service and waits until it is fully running.
    Args:
        config_path (str): The path to the WireGuard configuration file.
        timeout (int): Maximum time to wait for the service to start, in seconds.
        check_interval (int): Time to wait between status checks, in seconds.
    Returns:
        bool: True if the service was started successfully, False otherwise.
    """
    service_name = f"WireGuardTunnel${os.path.basename(config_path).split('.')[0]}"
    tunnel_name = f"{os.path.basename(config_path).split('.')[0]}"
    try:
        # Issue the start command
        subprocess.run(['sc', 'start', service_name], check=True)

        # Wait for the service to start
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = check_service_status(tunnel_name)
            if status == 'Running':
                print(f"Service {service_name} is running.")
                return True
            time.sleep(check_interval)
        print(f"Timeout: Service {service_name} did not start within {timeout} seconds.")
    except Exception as e:
        print(f"Failed to start VPN service: {e}")
    return False