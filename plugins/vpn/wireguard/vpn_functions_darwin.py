"""
VPN Functions for WireGuard on macOS
Author: Jacqueline Edoro
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

import sys
import os
import subprocess
import json
import tempfile
import re
from typing import Tuple, Optional

# Cache to map config names to actual utun interfaces (e.g., wg0 → utun6)
_interface_cache = {}

class HelperToolManager:
    """Manages XPC communication with the privileged helper via ResistCli"""
    
    def __init__(self):
        self.cli_path = self._find_cli_path()
        self.is_available = self.cli_path is not None
        print(f"🔍 [HELPER] CLI Path: {self.cli_path}")
        print(f"🔍 [HELPER] CLI Exists: {self.cli_path and os.path.exists(self.cli_path) if self.cli_path else False}")
    
    def _find_cli_path(self):
        """Locate ResistCli tool in the app bundle"""
        # When frozen (PyInstaller), look relative to the executable
        if getattr(sys, 'frozen', False):
            # sys.executable is in Contents/MacOS/
            macos_dir = os.path.dirname(sys.executable)
            app_contents = os.path.abspath(os.path.join(macos_dir, ".."))
            cli_path = os.path.join(app_contents, "Library", "LaunchServices", "ResistCli")
            if os.path.exists(cli_path):
                return cli_path
        
        # Development mode - search from script location
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        dev_cli_path = os.path.join(script_dir, "apple_helper", "cli", "ResistCli")
        if os.path.exists(dev_cli_path):
            return dev_cli_path
        
        return None
    

    


# Initialize helper manager
helper = HelperToolManager()

# Add VPN-specific helper methods
class VPNHelper:
    """VPN-specific operations using the XPC helper"""
    
    @staticmethod
    def start_vpn(config_path: str) -> Tuple[bool, str]:
        """Start VPN using config file"""
        if not helper.cli_path:
            return (False, "Helper CLI not found")
        
        try:
            result = subprocess.run(
                [helper.cli_path, "start-vpn", config_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout.strip() or result.stderr.strip()
            return (result.returncode == 0, output)
        except Exception as e:
            return (False, str(e))
    
    @staticmethod
    def stop_vpn(config_path: str) -> Tuple[bool, str]:
        """Stop VPN using config file"""
        if not helper.cli_path:
            return (False, "Helper CLI not found")
        
        try:
            result = subprocess.run(
                [helper.cli_path, "stop-vpn", config_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout.strip() or result.stderr.strip()
            return (result.returncode == 0, output)
        except Exception as e:
            return (False, str(e))
    
    @staticmethod
    def check_status(interface_name: str, test_ip: Optional[str] = None) -> Tuple[bool, str]:
        """Check VPN status"""
        if not helper.cli_path:
            print("⚠️ [HELPER] CLI path not available")
            return (False, "Stopped")
        
        try:
            cmd = [helper.cli_path, "status", interface_name]
            if test_ip:
                cmd.append(test_ip)
            
            print(f"🔍 [HELPER] Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout.strip()
            print(f"📊 [HELPER] Command result: returncode={result.returncode}, output='{output}'")
            
            # Status check returns "Running" or "Stopped"
            if "Running" in output:
                is_running = True
            else:
                is_running = False
            return (is_running, output)

        except subprocess.TimeoutExpired:
            print(f"⏰ [HELPER] Command timed out after 30 seconds")
            return (False, "Command timed out")
        except FileNotFoundError:
            print(f"❌ [HELPER] CLI executable not found: {helper.cli_path}")
            return (False, "Helper not available")
        except Exception as e:
            print(f"❌ [HELPER] Command error: {e}")
            return (False, str(e))

vpn_helper = VPNHelper()



def generate_keys():
    """Generate WireGuard keys (not implemented - use WireGuard command line tools)"""
    pass


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


def start_vpn(config_path):
    """Start VPN using the privileged helper"""
    
    
    success, output = vpn_helper.start_vpn(config_path)
    if success or "Interface for" in output:
        print(f"✅ VPN started: {output}")
        
        # Extract and cache the actual utun interface
        config_name = os.path.basename(config_path).replace('.conf', '')
        match = re.search(r'Interface for \S+ is (\S+)', output)
        if match:
            actual_interface = match.group(1)
            _interface_cache[config_name] = actual_interface
        
        return True
    else:
        print(f"❌ VPN start failed: {output}")
        return False


def stop_vpn(config_path):
    """Stop VPN using the privileged helper"""
    
    
    success, output = vpn_helper.stop_vpn(config_path)
    if success or "stopped" in output.lower():
        print(f"✅ VPN stopped: {output}")
        
        # Clear the cached interface mapping
        config_name = os.path.basename(config_path).replace('.conf', '')
        if config_name in _interface_cache:
            del _interface_cache[config_name]
        print(f"🔍 [CACHE] Cleared mapping for {config_name}")
        return True
    else:
        print(f"❌ VPN stop failed: {output}")
        return False




def check_service_status(interface_name, test_ip=None):
    """Check VPN status using the privileged helper
    
    Args:
        interface_name: Config name (e.g., 'wg0') or actual interface name (e.g., 'utun10')
        test_ip: Optional IP to ping for connectivity test
    """
    
    
    # Map config name to actual utun interface if available
    actual_interface = _interface_cache.get(interface_name, interface_name)
    
    # If the interface_name is already a utun interface (starts with 'utun'), use it directly
    if interface_name.startswith('utun'):
        actual_interface = interface_name
    
    print(f"🔍 [STATUS] Checking status for interface: {interface_name} -> {actual_interface}")
    try:
        # ✅ Don't pass test_ip to avoid ping tests
        is_running, status = vpn_helper.check_status(actual_interface, None)
        
        print(f"📊 [STATUS] Helper returned: is_running={is_running}, status='{status}'")
        
        return "Running" if is_running else "Stopped"
    
    except Exception as e:
        print(f"❌ [STATUS] Exception in check_service_status: {e}")
        import traceback
        traceback.print_exc()
        return "Stopped"


def check_wireguard_installed():
    """Check if WireGuard is available on the system"""
    print("🔍 [WIREGUARD] Checking WireGuard installation...")
    
    # Check for wg binary in system locations (same as Swift helper)
    wg_paths = [
        "/usr/bin/wg",              # System installation (macOS built-in)
        "/opt/homebrew/bin/wg",     # Apple Silicon Homebrew
        "/usr/local/bin/wg"         # Intel Homebrew
    ]
    
    wg_found = False
    wg_path = None
    for path in wg_paths:
        if os.path.exists(path):
            print(f"✅ WireGuard (wg) found at: {path}")
            wg_found = True
            wg_path = path
            break
    
    if not wg_found:
        print("❌ WireGuard (wg) not found in system locations")
        print("💡 Please install WireGuard:")
        print("   - Via Homebrew: brew install wireguard-tools")
        print("   - Or download from: https://www.wireguard.com/install/")
        return False
    
    # Check for wg-quick in system locations (same as Swift helper)
    wg_quick_paths = [
        "/usr/bin/wg-quick",          # System installation (macOS built-in)
        "/opt/homebrew/bin/wg-quick", # Apple Silicon Homebrew
        "/usr/local/bin/wg-quick"     # Intel Homebrew
    ]
    
    wg_quick_found = False
    wg_quick_path = None
    for path in wg_quick_paths:
        if os.path.exists(path):
            print(f"✅ WireGuard (wg-quick) found at: {path}")
            wg_quick_found = True
            wg_quick_path = path
            break
    
    if not wg_quick_found:
        print("❌ WireGuard (wg-quick) not found in system locations")
        print("💡 Please install WireGuard:")
        print("   - Via Homebrew: brew install wireguard-tools")
        print("   - Or download from: https://www.wireguard.com/install/")
        return False
    
    
    print("✅ WireGuard is properly installed and working on the system")
    return True
