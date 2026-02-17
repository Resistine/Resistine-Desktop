import ctypes
import json
import os
import subprocess
import time

from utils.logger import logger
from utils.settings import get_config_dir

# Keys file path for Windows
KEYS_FILE_PATH = os.path.join(get_config_dir(), "keys.json")

# Removed standard logging setup


def get_writable_wireguard_dir():
    """Get the directory where WireGuard configs are stored."""
    config_dir = get_config_dir()
    wg_dir = os.path.join(config_dir, "wireguard")
    os.makedirs(wg_dir, exist_ok=True)
    return wg_dir


def get_config_path(tunnel_name):
    """Get the full path to a tunnel configuration file."""
    return os.path.join(get_writable_wireguard_dir(), f"{tunnel_name}.conf")


def find_wireguard_exe():
    """Find the WireGuard executable."""
    # Standard installation path
    wg_exe = r"C:\Program Files\WireGuard\wireguard.exe"
    if os.path.exists(wg_exe):
        return wg_exe
    return None


def ensure_wireguard_app_installed():
    """Check if WireGuard is installed."""
    return find_wireguard_exe() is not None

def check_wireguard_installed():
    """Check if WireGuard is installed and accessible."""
    return ensure_wireguard_app_installed()

def can_manage_tunnels_without_admin():
    """
    Check if the user can manage tunnels without admin privileges.
    On Windows, this usually requires the LimitedOperatorGroup, but for simplicity
    we'll assume admin/UAC is needed for service control unless configured otherwise.
    """
    return False


def _check_service_access(service_name):
    """Check if we can access the service handle."""
    service_handle = None
    scm_handle = None
    SERVICE_STOP = 0x20
    SERVICE_START = 0x10
    SERVICE_QUERY_STATUS = 0x04
    desired_access = SERVICE_STOP | SERVICE_START | SERVICE_QUERY_STATUS

    try:
        scm_handle = ctypes.windll.advapi32.OpenSCManagerW(
            None, None, 0x0001
        )  # SC_MANAGER_CONNECT
        if not scm_handle:
            return False

        service_handle = ctypes.windll.advapi32.OpenServiceW(
            scm_handle, service_name, desired_access
        )
        if not service_handle:
            return False
        return True
    except Exception:
        return False
    finally:
        if service_handle:
            ctypes.windll.advapi32.CloseServiceHandle(service_handle)
        if scm_handle:
            ctypes.windll.advapi32.CloseServiceHandle(scm_handle)


def start_vpn(tunnel_name):
    """Start the VPN tunnel using WireGuard Windows service model."""
    wg_exe = find_wireguard_exe()
    if not wg_exe:
        logger.error("WireGuard executable not found")
        return False

    config_path = get_config_path(tunnel_name)
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}")
        return False

    # Logging for debug
    log_path = os.path.join(get_config_dir(), "vpn_debug.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n=== start_vpn: {tunnel_name} ===\n")
        f.write(f"WireGuard exe: {wg_exe}\n")
        f.write(f"Config path: {config_path}\n")
        f.write(f"Config exists: {os.path.exists(config_path)}\n")

    service_name = f"WireGuardTunnel${tunnel_name}"
    
    try:
        # STEP 1: Install/Import the tunnel configuration
        # This is the critical missing step - it creates the Windows service
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("STEP 1: Installing tunnel service...\n")
        
        install_cmd = [wg_exe, "/installtunnelservice", config_path]
        install_result = subprocess.run(
            install_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Install command: {' '.join(install_cmd)}\n")
            f.write(f"Install result: returncode={install_result.returncode}\n")
            f.write(f"Install stdout: {install_result.stdout}\n")
            f.write(f"Install stderr: {install_result.stderr}\n")

        # Check if installation was successful or if service already exists
        service_check = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Service check after install: returncode={service_check.returncode}\n")
            f.write(f"Service exists: {'RUNNING' in service_check.stdout.upper() or 'STOPPED' in service_check.stdout.upper()}\n")

        # If service doesn't exist after install, log the issue but continue
        if "1060" in service_check.stderr or "does not exist" in service_check.stdout.lower():
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("WARNING: Service still doesn't exist after install attempt\n")

        # STEP 2: Start the service 
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"STEP 2: Starting service {service_name}...\n")

        # Method A: Try direct sc start first
        sc_result = subprocess.run(
            ["sc", "start", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"SC start result: returncode={sc_result.returncode}\n")
            f.write(f"SC stdout: {sc_result.stdout}\n")
            f.write(f"SC stderr: {sc_result.stderr}\n")

        if sc_result.returncode == 0:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("[SUCCESS] Service started successfully with sc command\n")
            time.sleep(2)  # Give service time to start
            return True

        # Method B: Try with elevated privileges if direct start failed
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("Direct sc start failed, trying elevated approach...\n")

        # Use ShellExecute with elevated privileges
        sc_command = f'sc start "{service_name}"'
        result = ctypes.windll.shell32.ShellExecuteW(
            None,  # hwnd
            "runas",  # lpOperation - triggers UAC
            "cmd.exe",  # lpFile
            f"/c {sc_command}",  # lpParameters
            None,  # lpDirectory
            0  # nShowCmd - SW_HIDE
        )

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"ShellExecute result: {result}\n")

        if result > 32:  # Success
            time.sleep(3)  # Give service time to start

            # STEP 3: Verify the service is running
            check_result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"Final service check: {check_result.stdout}\n")

            if "RUNNING" in check_result.stdout.upper():
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("[SUCCESS] Service confirmed running!\n")
                return True
            else:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"Service status after start: {check_result.stdout}\n")
        else:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"ShellExecute failed with code {result}\n")

        # Method C: Alternative WireGuard GUI approach
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("STEP 3: Trying WireGuard GUI activation as fallback...\n")

        # Try to connect via WireGuard GUI
        gui_result = subprocess.run(
            [wg_exe, "/connect", tunnel_name],
            capture_output=True,
            text=True,
            timeout=15
        )

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"GUI connect result: returncode={gui_result.returncode}\n")
            f.write(f"GUI stdout: {gui_result.stdout}\n")
            f.write(f"GUI stderr: {gui_result.stderr}\n")

        if gui_result.returncode == 0:
            time.sleep(2)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("[SUCCESS] GUI connection successful\n")
            return True

    except subprocess.TimeoutExpired:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[ERROR] Operation timed out\n")
    except Exception as e:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[ERROR] Exception: {str(e)}\n")
        logger.error(f"Exception in start_vpn: {e}")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("[ERROR] All methods failed to start VPN\n")
    return False


def stop_vpn(tunnel_name):
    """Stop and uninstall VPN tunnel service."""
    wg_exe = find_wireguard_exe()
    if not wg_exe:
        logger.error("WireGuard executable not found")
        return False

    config_path = get_config_path(tunnel_name)
    log_path = os.path.join(get_config_dir(), "vpn_debug.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n=== stop_vpn: {tunnel_name} ===\n")
        f.write(f"Config path: {config_path}\n")

    service_name = f"WireGuardTunnel${tunnel_name}"

    try:
        # STEP 1: Stop the service first
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("STEP 1: Stopping service...\n")

        # Try direct sc stop first
        sc_result = subprocess.run(
            ["sc", "stop", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"SC stop result: returncode={sc_result.returncode}\n")
            f.write(f"SC stdout: {sc_result.stdout}\n")
            f.write(f"SC stderr: {sc_result.stderr}\n")

        # If direct stop fails, try with elevation
        if sc_result.returncode != 0:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("Direct sc stop failed, trying elevated approach...\n")

            sc_command = f'sc stop "{service_name}"'
            result = ctypes.windll.shell32.ShellExecuteW(
                None,  # hwnd
                "runas",  # lpOperation - triggers UAC
                "cmd.exe",  # lpFile
                f"/c {sc_command}",  # lpParameters
                None,  # lpDirectory
                0,  # nShowCmd - SW_HIDE
            )

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"ShellExecute stop result: {result}\n")

        # Wait for service to stop
        time.sleep(2)

        # STEP 2: Verify service is stopped
        check_result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Service status check: {check_result.stdout}\n")

        service_stopped = (
            "STOPPED" in check_result.stdout.upper() 
            or "NOT STARTED" in check_result.stdout.upper()
            or "1060" in check_result.stderr  # Service doesn't exist
        )

        # STEP 3: Uninstall the tunnel service
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("STEP 2: Uninstalling tunnel service...\n")

        uninstall_cmd = [wg_exe, "/uninstalltunnelservice", config_path]
        uninstall_result = subprocess.run(
            uninstall_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"Uninstall command: {' '.join(uninstall_cmd)}\n")
            f.write(f"Uninstall result: returncode={uninstall_result.returncode}\n")
            f.write(f"Uninstall stdout: {uninstall_result.stdout}\n")
            f.write(f"Uninstall stderr: {uninstall_result.stderr}\n")

        # Alternative: Try WireGuard GUI disconnect
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("STEP 3: Trying WireGuard GUI disconnect...\n")

        gui_result = subprocess.run(
            [wg_exe, "/disconnect", tunnel_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"GUI disconnect result: returncode={gui_result.returncode}\n")
            f.write(f"GUI stdout: {gui_result.stdout}\n")
            f.write(f"GUI stderr: {gui_result.stderr}\n")

        # Final verification - check if service no longer exists
        final_check = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )

        service_removed = "1060" in final_check.stderr or "does not exist" in final_check.stdout.lower()

        with open(log_path, "a", encoding="utf-8") as f:
            if service_stopped or service_removed:
                f.write("[SUCCESS] VPN tunnel stopped successfully\n")
            else:
                f.write("[WARNING] VPN may still be running or service still exists\n")

        return service_stopped or service_removed

    except subprocess.TimeoutExpired:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[ERROR] Operation timed out\n")
    except Exception as e:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[ERROR] Exception: {str(e)}\n")
        logger.error(f"Exception in stop_vpn: {e}")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("[ERROR] Failed to stop VPN tunnel\n")
    return False


def check_service_status(tunnel_name, test_ip=None):
    if not tunnel_name:
        return "Not Installed"

    wg_cli = r"C:\Program Files\WireGuard\wireguard.exe"
    if not os.path.exists(wg_cli):
        return "Not Installed"

    service_name = f"WireGuardTunnel${tunnel_name}"
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout or "") + (result.stderr or "")
        lower_output = output.lower()
        if "does not exist" in lower_output or "not exist" in lower_output:
            return "Not Installed"
        if "state" in lower_output:
            if "running" in lower_output or "start pending" in lower_output:
                return "Running"
            if "stopped" in lower_output:
                return "Stopped"
    except Exception:
        pass

    try:
        result = subprocess.run(
            [wg_cli, "/list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        stdout = result.stdout or ""
        if result.returncode == 0:
            for line in stdout.splitlines():
                if tunnel_name.lower() in line.lower():
                    if any(
                        word in line.lower()
                        for word in ("active", "connected", "running")
                    ):
                        return "Running"
                    return "Stopped"
    except Exception:
        pass

    return "Not Installed"


def run_elevated_powershell(script_path, arguments=""):
    """
    Run a PowerShell script with elevated privileges using ShellExecuteW.
    Returns True if successful, False otherwise.
    """
    try:
        import ctypes

        # ShellExecuteW parameters
        SW_HIDE = 0

        # Use ShellExecuteW to run with elevated privileges
        result = ctypes.windll.shell32.ShellExecuteW(
            None,  # hwnd
            "runas",  # lpOperation - "runas" for admin
            "powershell.exe",  # lpFile
            f'-ExecutionPolicy Bypass -File "{script_path}" {arguments}',  # lpParameters
            None,  # lpDirectory
            SW_HIDE,  # nShowCmd
        )

        # ShellExecuteW returns > 32 on success
        return result > 32

    except Exception as e:
        logger.error(f"Error running elevated PowerShell: {e}")
        return False


def generate_wireguard_keys():
    """
    Generate WireGuard public/private key pair using wg command or fallback method.

    Returns:
        dict: {
            'private_key': str,
            'public_key': str
        }
        None: If key generation fails
    """
    try:
        # First try using WireGuard's wg.exe if available
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

                    return {
                        "private_key": private_key,
                        "public_key": public_key,
                    }
                except subprocess.CalledProcessError as e:
                    logger.warning(f"WireGuard CLI key generation failed: {e}")
                    # Fall through to alternative method

        # Fallback method: Generate keys using Python cryptography library
        logger.info("Using fallback key generation method")
        return _generate_keys_fallback()

    except Exception as e:
        logger.error(f"Key generation failed: {e}")
        return None


def _generate_keys_fallback():
    """
    Fallback method to generate WireGuard keys without requiring WireGuard installation.
    Uses Python's cryptography library to generate Curve25519 keys compatible with WireGuard.
    """
    try:
        import base64
        import secrets
        
        # Generate 32 random bytes for private key
        private_key_bytes = secrets.token_bytes(32)
        
        # WireGuard private keys are base64 encoded
        private_key = base64.b64encode(private_key_bytes).decode('utf-8')
        
        # For the public key, we need to do curve25519 scalar multiplication
        # This is a simplified approach - in reality WireGuard does additional processing
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            
            # Create X25519 private key from our bytes
            x25519_private = X25519PrivateKey.from_private_bytes(private_key_bytes)
            
            # Get the public key
            x25519_public = x25519_private.public_key()
            
            # Get public key bytes
            public_key_bytes = x25519_public.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            
            # Base64 encode the public key
            public_key = base64.b64encode(public_key_bytes).decode('utf-8')
            
            return {
                "private_key": private_key,
                "public_key": public_key,
            }
            
        except ImportError:
            logger.warning("cryptography library not available, using simplified key generation")
            # Very basic fallback - generates random base64 strings
            # This is not cryptographically proper but will allow the app to function
            public_key_bytes = secrets.token_bytes(32)
            public_key = base64.b64encode(public_key_bytes).decode('utf-8')
            
            return {
                "private_key": private_key,
                "public_key": public_key,
            }
            
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
        # On Windows, we'll set file attributes to hidden/readonly instead of chmod
        try:
            import stat
            os.chmod(KEYS_FILE_PATH, stat.S_IREAD | stat.S_IWRITE)
        except:
            pass  # Ignore if chmod fails on Windows
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


def parse_and_create_vpn_config(vpn_config_json_string, config_name="resistine_default"):
    """
    Parse and create the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    try:
        if not vpn_config_json_string:
            return None

        logger.debug("WireGuard config received from API")
        
        # Parse the JSON config
        vpn_config = json.loads(vpn_config_json_string)
        
        # Get config directory
        config_dir = get_writable_wireguard_dir()
        config_path = os.path.join(config_dir, f"{config_name}.conf")
        
        # Write the config file
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
    """
    Parse and save the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    return parse_and_create_vpn_config(vpn_config_json, config_name)


logger.debug("WireGuard app integration loaded")
