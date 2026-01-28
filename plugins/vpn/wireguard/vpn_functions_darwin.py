"""
VPN Functions for WireGuard on macOS
Author: Jacqueline Edoro
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json
import os
import platform
import re
import subprocess
import sys
from typing import Optional, Tuple

from utils import settings
from utils.settings import get_config_dir
from utils.logger import logger


def get_writable_wireguard_dir():
    """Get a writable directory for WireGuard configuration files"""
    wireguard_dir = os.path.join(get_config_dir(), "wireguard")
    os.makedirs(wireguard_dir, exist_ok=True)
    return wireguard_dir





# Cache to map config names to actual utun interfaces (e.g., wg0 → utun6)
_interface_cache = {}


class HelperToolManager:
    """Manages XPC communication with the privileged helper via ResistCli"""

    def __init__(self):
        self.cli_path = self._find_cli_path()
        self.is_available = self.cli_path is not None
        logger.info(f"🔍 [HELPER] CLI Path: {self.cli_path}")
        logger.info(
            f"🔍 [HELPER] CLI Exists: {self.cli_path and os.path.exists(self.cli_path) if self.cli_path else False}"
        )

    def _find_cli_path(self):
        """Locate ResistCli tool in the app bundle"""
        # When frozen (PyInstaller), look relative to the executable
        if getattr(sys, "frozen", False):
            # sys.executable is in Contents/MacOS/
            macos_dir = os.path.dirname(sys.executable)
            app_contents = os.path.abspath(os.path.join(macos_dir, ".."))
            cli_path = os.path.join(
                app_contents, "Library", "LaunchServices", "ResistCli"
            )
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
                timeout=30,
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
                timeout=30,
            )
            output = result.stdout.strip() or result.stderr.strip()
            return (result.returncode == 0, output)
        except Exception as e:
            return (False, str(e))

    @staticmethod
    def check_status(
        interface_name: str, test_ip: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Check VPN status"""
        if not helper.cli_path:
            logger.warning("⚠️ [HELPER] CLI path not available")
            return (False, "Stopped")

        try:
            cmd = [helper.cli_path, "status", interface_name]
            if test_ip:
                cmd.append(test_ip)

            logger.info(f"🔍 [HELPER] Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout.strip()
            logger.info(
                f"📊 [HELPER] Command result: returncode={result.returncode}, output='{output}'"
            )

            # Status check returns "Running" or "Stopped"
            if "Running" in output:
                is_running = True
            else:
                is_running = False
            return (is_running, output)

        except subprocess.TimeoutExpired:
            logger.error(f"⏰ [HELPER] Command timed out after 30 seconds")
            return (False, "Command timed out")
        except FileNotFoundError:
            logger.error(f"❌ [HELPER] CLI executable not found: {helper.cli_path}")
            return (False, "Helper not available")
        except Exception as e:
            logger.error(f"❌ [HELPER] Command error: {e}")
            return (False, str(e))


vpn_helper = VPNHelper()

# Keychain Management Functions


# Key management functions removed - replaced by utils.settings


def save_wireguard_keys(private_key, public_key):
    """
    Save WireGuard keys.

    Args:
        private_key: WireGuard private key (string)
        public_key: WireGuard public key (string)

    Returns:
        bool: True if successful, False otherwise
    """
    p1 = settings.set_secret("wireguard", "private_key", private_key)
    p2 = settings.set_secret("wireguard", "public_key", public_key)
    return p1 and p2


def get_wireguard_private_key():
    """Get WireGuard private key from Keychain"""
    return settings.get_secret("wireguard", "private_key")


def get_wireguard_public_key():
    """Get WireGuard public key from Keychain"""
    return settings.get_secret("wireguard", "public_key")


def delete_wireguard_keys():
    """
    Delete WireGuard keys from Keychain (for key regeneration)

    Returns:
        bool: True if successful, False otherwise
    """
    d1 = settings.delete("wireguard", "private_key")
    d2 = settings.delete("wireguard", "public_key")
    return d1 and d2


def wireguard_keys_exist():
    """Check if WireGuard keys exist in Keychain"""
    private_key = settings.get_secret("wireguard", "private_key")
    public_key = settings.get_secret("wireguard", "public_key")
    return bool(private_key and public_key)


def generate_wireguard_keys():
    """
    Generate WireGuard public/private key pair.

    WireGuard keys are:
    - Private key: 32 bytes, base64-encoded (44 characters)
    - Public key: 32 bytes, base64-encoded (44 characters), derived from private key

    Returns:
        dict: {
            'private_key': str,   # Base64-encoded private key (44 chars)
            'public_key': str     # Base64-encoded public key (44 chars)
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
        logger.error(f"❌ Key generation command failed: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Key generation failed: {e}")
        return None


def start_vpn(config_path):
    """Start VPN using the privileged helper"""

    success, output = vpn_helper.start_vpn(config_path)
    if success or "Interface for" in output:
        logger.info(f"✅ VPN started: {output}")

        # Extract and cache the actual utun interface
        config_name = os.path.basename(config_path).replace(".conf", "")
        match = re.search(r"Interface for \S+ is (\S+)", output)
        if match:
            actual_interface = match.group(1)
            _interface_cache[config_name] = actual_interface

        return True
    else:
        logger.error(f"❌ VPN start failed: {output}")
        return False


def stop_vpn(config_path):
    """Stop VPN using the privileged helper"""

    success, output = vpn_helper.stop_vpn(config_path)
    if success or "stopped" in output.lower():
        logger.info(f"✅ VPN stopped: {output}")

        # Clear the cached interface mapping
        config_name = os.path.basename(config_path).replace(".conf", "")
        if config_name in _interface_cache:
            del _interface_cache[config_name]
        logger.info(f"🔍 [CACHE] Cleared mapping for {config_name}")
        return True
    else:
        logger.error(f"❌ VPN stop failed: {output}")
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
    if interface_name.startswith("utun"):
        actual_interface = interface_name

    logger.info(
        f"🔍 [STATUS] Checking status for interface: {interface_name} -> {actual_interface}"
    )
    try:
        # ✅ Don't pass test_ip to avoid ping tests
        is_running, status = vpn_helper.check_status(actual_interface, None)

        logger.info(
            f"📊 [STATUS] Helper returned: is_running={is_running}, status='{status}'"
        )

        return "Running" if is_running else "Stopped"

    except Exception as e:
        logger.error(f"❌ [STATUS] Exception in check_service_status: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return "Stopped"


def check_wireguard_installed():
    """Check if WireGuard is available on the system"""
    logger.info("🔍 [WIREGUARD] Checking WireGuard installation...")

    # Check for wg binary in system locations (same as Swift helper)
    wg_paths = [
        "/usr/bin/wg",  # System installation (macOS built-in)
        "/opt/homebrew/bin/wg",  # Apple Silicon Homebrew
        "/usr/local/bin/wg",  # Intel Homebrew
    ]

    wg_found = False
    wg_path = None
    for path in wg_paths:
        if os.path.exists(path):
            logger.info(f"✅ WireGuard (wg) found at: {path}")
            wg_found = True
            wg_path = path
            break

    if not wg_found:
        logger.error("❌ WireGuard (wg) not found in system locations")
        logger.info("💡 Please install WireGuard:")
        logger.info("   - Via Homebrew: brew install wireguard-tools")
        logger.info("   - Or download from: https://www.wireguard.com/install/")
        return False

    # Check for wg-quick in system locations (same as Swift helper)
    wg_quick_paths = [
        "/usr/bin/wg-quick",  # System installation (macOS built-in)
        "/opt/homebrew/bin/wg-quick",  # Apple Silicon Homebrew
        "/usr/local/bin/wg-quick",  # Intel Homebrew
    ]

    wg_quick_found = False
    wg_quick_path = None
    for path in wg_quick_paths:
        if os.path.exists(path):
            logger.info(f"✅ WireGuard (wg-quick) found at: {path}")
            wg_quick_found = True
            wg_quick_path = path
            break

    if not wg_quick_found:
        logger.error("❌ WireGuard (wg-quick) not found in system locations")
        logger.info("💡 Please install WireGuard:")
        logger.info("   - Via Homebrew: brew install wireguard-tools")
        logger.info("   - Or download from: https://www.wireguard.com/install/")
        return False

    logger.info("✅ WireGuard is properly installed and working on the system")
    return True


def parse_and_create_vpn_config(vpn_config_json_string, config_name="wg0"):
    """
    Parse VPN configuration from server response and create WireGuard config file.

    Args:
        vpn_config_json_string: JSON string containing VPN config from server
        config_name: Name for the config file (default: "wg0")

    Returns:
        str: Path to created config file, or None if failed

    Expected JSON structure:
    {
        "Peer": {
            "PublicKey": "...",
            "AllowedIPs": ["10.49.0.0/17"],
            "Endpoint": "18.199.109.145:987"
        },
        "Interface": {
            "PrivateKey": "",  # Empty, will use from keychain
            "Address": "10.49.65.6",
            "DNS": ["10.49.11.10"]  # Uses DNS_SERVER constant (see top of file)
        }
    }
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
            logger.error("❌ Error: Private key not found in keychain")
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

        # Get writable WireGuard directory
        wireguard_dir = get_writable_wireguard_dir()

        # Create config file path
        config_filename = f"{config_name}.conf"
        config_path = os.path.join(wireguard_dir, config_filename)

        # Write config file
        with open(config_path, "w") as config_file:
            config_file.write(config_content)

        # Set strict permissions (600) to avoid "world accessible" warning
        os.chmod(config_path, 0o600)

        logger.info(f"✅ WireGuard config created at: {config_path}")
        logger.info(f"   Server: {endpoint}")
        logger.info(f"   Client IP: {client_address}")
        logger.info(f"   DNS: {dns_str}")

        return config_path

    except json.JSONDecodeError as e:
        logger.error(f"❌ Error parsing VPN config JSON: {e}")
        return None
    except KeyError as e:
        logger.error(f"❌ Error: Missing required field in VPN config: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error creating VPN config: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return None


def setup_vpn_keys():
    """
    Generate and save new WireGuard keys for the session.
    Returns the public key if successful, None otherwise.
    """
    try:
        # Step 1: Regenerate fresh keys for this sign-in session
        # Delete old keys (if they exist) to ensure fresh key pair
        logger.info("Regenerating WireGuard keys for new login session")
        delete_wireguard_keys()

        # Generate new key pair
        keys = generate_wireguard_keys()
        if not keys:
            logger.error("❌ Failed to generate keys")
            return None

        # Save both private and public keys to Keychain with iOS-compatible service names
        if not save_wireguard_keys(keys["private_key"], keys["public_key"]):
            logger.error("❌ Failed to save keys securely")
            return None

        # Get public key for API transmission
        public_key = keys["public_key"]

        if not public_key:
            logger.error("❌ Failed to get public key")
            return None

        logger.info(f"✅ WireGuard Public Key Validated: Length={len(public_key)} characters")
        return public_key

    except Exception as e:
        logger.error(f"❌ Error setting up VPN keys: {e}")
        return None


def save_vpn_configuration(vpn_config_json):
    """
    Parse and save the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    try:
        if not vpn_config_json:
            return None

        logger.info("WireGuard config received from API")

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
            logger.error(f"Error parsing VPN config for logging: {e}")

        # Create config file
        config_path = parse_and_create_vpn_config(vpn_config_json, config_name="wg0")

        if config_path:
            logger.info("✅ VPN configuration saved successfully")
            return config_path
        else:
            logger.error("❌ Failed to create VPN config")
            return None

    except Exception as e:
        logger.error(f"❌ Error creating VPN config: {e}")
        return None


def ensure_helper_registered():
    """Register the privileged helper on macOS (runs silently on startup)"""
    import sys
    import os

    # Skip registration if running from source (SMAppService requires a bundle)
    # We check for the presence of 'Contents/MacOS' in the executable path
    if not (".app/Contents/MacOS" in sys.executable or ".app/Contents/MacOS" in os.path.abspath(sys.argv[0])):
        logger.debug("ℹ️ Skipping helper registration (not running as an app bundle)")
        return

    try:
        from ServiceManagement import SMAppService

        plist_name = "com.resistine.plist"

        # Create the service
        try:
            service = SMAppService.daemonServiceWithPlistName_(plist_name)
        except:
            try:
                service = SMAppService.daemonWithPlistName_(plist_name)
            except:
                logger.warning("⚠️ Could not create SMAppService for helper")
                return

        # Check current status
        status = int(service.status())
        status_map = {
            0: "notRegistered",
            1: "enabled",
            2: "requiresApproval",
            3: "notFound",
        }
        status_str = status_map.get(status, "unknown")

        if status == 1:  # Already enabled
            logger.info("✅ Helper already enabled")
            return

        if status == 2:  # Requires approval
            logger.warning("⚠️ Helper registered but requires user approval")
            prompt_helper_approval(service)
            return

        # Not registered yet (0 or 3), try to register
        logger.info("🔧 Registering privileged helper...")
        error = service.registerAndReturnError_(None)

        if error:
            logger.error(f"⚠️ Helper registration error: {error}")
            # Check status again after registration attempt
            new_status = int(service.status())
            if new_status == 2:  # Now requires approval
                prompt_helper_approval(service)
        else:
            logger.info("✅ Helper registered successfully")

    except ImportError:
        logger.warning("⚠️ ServiceManagement framework not available")
    except Exception as e:
        logger.error(f"⚠️ Helper registration error: {e}")


def prompt_helper_approval(service):
    """Prompt user to approve helper in System Settings"""
    try:
        from gui.dialogs import ask_yes_no
        import tkinter as tk
        
        # Try to find the root window
        try:
            root = tk._default_root
        except:
            root = None

        def on_confirm(confirmed):
            if confirmed:
                # Open System Settings → Login Items
                service.openSystemSettingsLoginItems()
                logger.info("📱 Opened System Settings → Login Items")

        ask_yes_no(
            root,
            "Helper Approval Required",
            "Resistine needs your approval to install a helper tool for VPN functionality.\n\n"
            "Click 'Yes' to open System Settings where you can enable it in Login Items.",
            on_confirm
        )
    except Exception as e:
        logger.error(f"⚠️ Could not prompt for approval: {e}")
    except Exception as e:
        logger.error(f"⚠️ Could not prompt for approval: {e}")
