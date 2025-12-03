import os
import subprocess
import ctypes
import time
import logging
from utils.settings import get_config_dir

# Configure logging
logger = logging.getLogger(__name__)

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
        scm_handle = ctypes.windll.advapi32.OpenSCManagerW(None, None, 0x0001)  # SC_MANAGER_CONNECT
        if not scm_handle:
            return False

        service_handle = ctypes.windll.advapi32.OpenServiceW(scm_handle, service_name, desired_access)
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
    """Start the VPN tunnel."""
    wg_exe = find_wireguard_exe()
    if not wg_exe:
        if not ensure_wireguard_app_installed():
            return False
        wg_exe = find_wireguard_exe()
        if not wg_exe:
            return False
    
    manage_without_admin = can_manage_tunnels_without_admin()
    config_path = get_config_path(tunnel_name)
    
    # Logging for debug
    log_path = os.path.join(get_config_dir(), "vpn_debug.log")
    with open(log_path, "a") as f:
        f.write(f"start_vpn: can_manage = {manage_without_admin}, config_path_exists = {os.path.exists(config_path)}\n")

    service_name = f"WireGuardTunnel${tunnel_name}"
    
    if not _check_service_access(service_name):
        with open(log_path, "a") as f:
            f.write("start_vpn: service access denied (QueryServiceStatusEx failed), will attempt operation anyway\n")
        try:
            diag = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            diag_output = (diag.stdout or "") + (diag.stderr or "")
        except Exception as diag_error:
            diag_output = f"sc query diagnostic failed: {diag_error}"
        
        with open(log_path, "a") as f:
            f.write(f"start_vpn: sc query diagnostic -> {diag_output.strip()}\n")
            
        if "1060" in diag_output:
            with open(log_path, "a") as f:
                f.write("start_vpn: service missing, cannot proceed\n")
            return False

    try:
        # Use ShellExecute to properly trigger UAC prompts for admin elevation
        with open(log_path, "a") as f:
            f.write("start_vpn: attempting to start service with potential UAC prompt\n")

        # Use ShellExecuteW to run sc start with admin privileges if needed
        sc_command = f"sc start \"{service_name}\""
        result = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # lpOperation - "runas" triggers UAC
            "cmd.exe",      # lpFile
            f"/c {sc_command}",  # lpParameters
            None,           # lpDirectory
            0               # nShowCmd - SW_HIDE
        )

        with open(log_path, "a") as f:
            f.write(f"start_vpn: ShellExecute result={result}\n")

        # ShellExecute returns > 32 on success, <= 32 on error
        if result > 32:
            # Wait a moment for the service to start
            time.sleep(2)

            # Check if service actually started
            check_result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            check_output = (check_result.stdout or "") + (check_result.stderr or "")
            if "RUNNING" in check_output.upper():
                with open(log_path, "a") as f:
                    f.write("start_vpn: service successfully started\n")
                return True
            else:
                with open(log_path, "a") as f:
                    f.write(f"start_vpn: service status check failed: {check_output.strip()}\n")
        else:
            with open(log_path, "a") as f:
                f.write(f"start_vpn: ShellExecute failed with code {result}\n")

    except subprocess.TimeoutExpired:
        with open(log_path, "a") as f:
            f.write("start_vpn: service status check timed out\n")
    except Exception as e:
        with open(log_path, "a") as f:
            f.write(f"start_vpn: exception during start operation: {str(e)}\n")

    with open(log_path, "a") as f:
        f.write("start_vpn: failed to start tunnel via service control\n")
    return False

def stop_vpn(tunnel_name):
    """Stop VPN using WireGuard app."""
    wg_exe = find_wireguard_exe()
    if not wg_exe:
        return False
    
    manage_without_admin = can_manage_tunnels_without_admin()
    config_path = get_config_path(tunnel_name)
    
    log_path = os.path.join(get_config_dir(), "vpn_debug.log")
    with open(log_path, "a") as f:
        f.write(f"stop_vpn: can_manage = {manage_without_admin}, config_path_exists = {os.path.exists(config_path)}\n")

    service_name = f"WireGuardTunnel${tunnel_name}"
    
    if not _check_service_access(service_name):
        with open(log_path, "a") as f:
            f.write("stop_vpn: service access denied (QueryServiceStatusEx failed), will attempt operation anyway\n")
        try:
            diag = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            diag_output = (diag.stdout or "") + (diag.stderr or "")
        except Exception as diag_error:
            diag_output = f"sc query diagnostic failed: {diag_error}"
        with open(log_path, "a") as f:
            f.write(f"stop_vpn: sc query diagnostic -> {diag_output.strip()}\n")
        if "1060" in diag_output:
            with open(log_path, "a") as f:
                f.write("stop_vpn: service missing, cannot proceed\n")
            return False

    try:
        # Use ShellExecute to properly trigger UAC prompts for admin elevation
        with open(log_path, "a") as f:
            f.write("stop_vpn: attempting to stop service with potential UAC prompt\n")

        # Use ShellExecuteW to run sc stop with admin privileges if needed
        sc_command = f"sc stop \"{service_name}\""
        result = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # lpOperation - "runas" triggers UAC
            "cmd.exe",      # lpFile
            f"/c {sc_command}",  # lpParameters
            None,           # lpDirectory
            0               # nShowCmd - SW_HIDE
        )

        with open(log_path, "a") as f:
            f.write(f"stop_vpn: ShellExecute result={result}\n")

        # ShellExecute returns > 32 on success, <= 32 on error
        if result > 32:
            # Wait a moment for the service to stop
            time.sleep(2)

            # Check if service actually stopped
            check_result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            check_output = (check_result.stdout or "") + (check_result.stderr or "")
            if "STOPPED" in check_output.upper() or "NOT STARTED" in check_output.upper():
                with open(log_path, "a") as f:
                    f.write("stop_vpn: service successfully stopped\n")
                return True
            else:
                with open(log_path, "a") as f:
                    f.write(f"stop_vpn: service status check failed: {check_output.strip()}\n")
        else:
            with open(log_path, "a") as f:
                f.write(f"stop_vpn: ShellExecute failed with code {result}\n")

    except subprocess.TimeoutExpired:
        with open(log_path, "a") as f:
            f.write("stop_vpn: service status check timed out\n")
    except Exception as e:
        with open(log_path, "a") as f:
            f.write(f"stop_vpn: exception during stop operation: {str(e)}\n")

    with open(log_path, "a") as f:
        f.write("stop_vpn: failed to stop tunnel via service control\n")
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
                    if any(word in line.lower() for word in ("active", "connected", "running")):
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
        from ctypes import wintypes

        # ShellExecuteW parameters
        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0

        # Build the command
        command = f'powershell.exe -ExecutionPolicy Bypass -File "{script_path}" {arguments}'

        # Use ShellExecuteW to run with elevated privileges
        result = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # lpOperation - "runas" for admin
            "powershell.exe", # lpFile
            f'-ExecutionPolicy Bypass -File "{script_path}" {arguments}', # lpParameters
            None,           # lpDirectory
            SW_HIDE         # nShowCmd
        )

        # ShellExecuteW returns > 32 on success
        return result > 32

    except Exception as e:
        print(f"Error running elevated PowerShell: {e}")
        return False

print("✅ WireGuard app integration loaded")