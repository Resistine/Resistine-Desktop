"""
VPN Functions for WireGuard on Darwin (AppleScript Version)
----------------------------------------------------------
Uses AppleScript (osascript) for privileged operations instead of direct sudo commands.
"""

import sys
import os
import subprocess
import json
import tempfile
from typing import Tuple, Optional

_stored_password = None
def _request_password_once():
    """Request password once and store it for future use"""
    global _stored_password
    
    if _stored_password is not None:
        return _stored_password
    
    try:
        # Request password using AppleScript
        apple_script = '''
        tell application "System Events"
            activate
            set thePassword to display dialog "Resistine Desktop needs administrator privileges to manage VPN connections. Please enter your password:" default answer "" with title "Administrator Password Required" with icon caution with hidden answer
            return text returned of thePassword
        end tell
        '''
        
        result = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            _stored_password = result.stdout.strip()
            print("✅ Password stored for VPN operations")
            return _stored_password
        else:
            print("❌ Password request cancelled or failed")
            return None
            
    except Exception as e:
        print(f"❌ Error requesting password: {e}")
        return None
def _run_wireguard_command(command: list, description: str = "This operation requires administrator privileges") -> Tuple[bool, str]:
    """Run WireGuard command with stored password"""
    global _stored_password
    
    # Get password if not already stored
    if _stored_password is None:
        password = _request_password_once()
        if password is None:
            return False, "Password required but not provided"
    
    try:
        # Create a temporary script file to avoid escaping issues
        script_content = f'''#!/bin/bash
# {description}
# Ensure we use bash 4+ and set proper environment
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export SHELL="/bin/bash"

# Run the command with proper argument handling
{" ".join(f'"{arg}"' if ' ' in arg else arg for arg in command)}
'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(script_content)
            script_path = f.name
        
        # Make script executable
        os.chmod(script_path, 0o755)
        
        # Run with stored password using echo and sudo
        sudo_command = f'echo "{_stored_password}" | sudo -S /bin/bash {script_path}'
        
        result = subprocess.run(
            ["/bin/bash", "-c", sudo_command],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Clean up
        try:
            os.unlink(script_path)
        except:
            pass
        
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            # If password is wrong, clear it and try again
            if "incorrect password" in result.stderr.lower() or "authentication failure" in result.stderr.lower():
                _stored_password = None
                print("❌ Incorrect password, please try again")
            return False, result.stderr.strip()
            
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)

def generate_keys():
    """Generate WireGuard private and public keys using AppleScript."""
    try:
        # Find wg path
        wg_path = _find_wireguard_path("wg")
        if not wg_path:
            print("❌ WireGuard not found")
            return None
        
        # Generate private key using AppleScript
        success, private_key = _run_wireguard_command([wg_path, "genkey"], "Generate WireGuard private key")
        if not success:
            print(f"❌ Failed to generate private key: {private_key}")
            return None
        
        private_key = private_key.strip()
        
        # Generate public key from private key
        try:
            result = subprocess.run(
                [wg_path, "pubkey"],
                input=private_key,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                public_key = result.stdout.strip()
            else:
                print(f"❌ Failed to generate public key: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"❌ Exception generating public key: {e}")
            return None

        keys = {
            "private_key": private_key,
            "public_key": public_key
        }

        script_dir = os.path.dirname(__file__)
        keys_path = os.path.join(script_dir, "keys.json")
        with open(keys_path, "w") as json_file:
            json.dump(keys, json_file, indent=4)

        print("Keys generated successfully.")
        return keys
    except Exception as e:
        print(f"Error generating keys: {e}")
        return None

# Updated functions using AppleScript
def start_vpn(config_path):
    """Start the WireGuard VPN service using AppleScript."""
    try:
        # Find wg-quick path
        wg_quick_path = _find_wireguard_path("wg-quick")
        if not wg_quick_path:
            print("❌ WireGuard not found")
            return False
        
        # Check if config file exists
        if not os.path.exists(config_path):
            print(f"❌ Config file not found: {config_path}")
            return False
        
        # Extract interface name from config path
        interface_name = os.path.splitext(os.path.basename(config_path))[0]
        
        # Copy config to system location for wg-quick
        system_config_dir = "/opt/homebrew/etc/wireguard"
        system_config_path = os.path.join(system_config_dir, f"{interface_name}.conf")
        
        # Create system config directory if it doesn't exist
        success, _ = _run_wireguard_command(["mkdir", "-p", system_config_dir], "Create WireGuard config directory")
        if not success:
            print(f"❌ Failed to create config directory: {system_config_dir}")
            return False
        
        # Copy config file to system location
        success, _ = _run_wireguard_command(["cp", config_path, system_config_path], "Copy config to system location")
        if not success:
            print(f"❌ Failed to copy config to system location")
            return False
        
        # Run wg-quick up command using interface name
        success, output = _run_wireguard_command([wg_quick_path, "up", interface_name], "Start WireGuard VPN")
        
        if success:
            print("✅ VPN started successfully")
            return True
        else:
            # Check if the interface already exists and is running
            if "already exists" in output:
                print("✅ VPN is already running")
                return True
            else:
                print(f"❌ Failed to start VPN: {output}")
                return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def stop_vpn(config_path):
    """Stop the WireGuard VPN service using AppleScript."""
    try:
        # Find wg-quick path
        wg_quick_path = _find_wireguard_path("wg-quick")
        if not wg_quick_path:
            print("❌ WireGuard not found")
            return False
        
        # Extract interface name from config path
        interface_name = os.path.splitext(os.path.basename(config_path))[0]
        
        # Run wg-quick down command using interface name
        success, output = _run_wireguard_command([wg_quick_path, "down", interface_name], "Stop WireGuard VPN")
        
        if success:
            print("✅ VPN stopped successfully")
            return True
        else:
            print(f"❌ Failed to stop VPN: {output}")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def check_service_status(interface_name, test_ip):
    """Check the status of the WireGuard VPN service using AppleScript."""
    try:
        # Find wg path
        wg_path = _find_wireguard_path("wg")
        if not wg_path:
            return "Stopped"
        
        # Run wg show command using AppleScript
        success, output = _run_wireguard_command([wg_path, "show"], "Check WireGuard status")
        
        if success and output.strip():
            # Check if there are active interfaces
            lines = output.split('\n')
            for line in lines:
                if "interface:" in line and "utun" in line:
                    return "Running"
        
        return "Stopped"
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return "Stopped"
def _find_wireguard_path(tool: str) -> Optional[str]:
    """Find WireGuard tool path"""
    search_paths = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin"
    ]
    
    for path in search_paths:
        full_path = os.path.join(path, tool)
        if os.path.exists(full_path) and os.access(full_path, os.X_OK):
            return full_path
    
    return None

def check_wireguard_installed():
    """Check if WireGuard is installed."""
    try:
        wg_path = _find_wireguard_path("wg")
        wg_quick_path = _find_wireguard_path("wg-quick")
        print(f"wg_path: {wg_path}")
        print(f"wg_quick_path: {wg_quick_path}")
        if wg_path and wg_quick_path:
            return True
        return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

# Keep utility functions
def is_admin():
    """Check if the script is running with root privileges."""
    return os.geteuid() == 0

def run_as_admin(command):
    """Run a command with administrator privileges using AppleScript."""
    try:
        success, output = _run_wireguard_command(command, "Run command with administrator privileges")
        return success
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def run_installer_as_admin(installer_path):
    """Run an installer with administrator privileges using AppleScript."""
    try:
        success, output = _run_wireguard_command([installer_path], "Run installer with administrator privileges")
        return success
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False
