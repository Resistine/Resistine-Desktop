    service_handle = None
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
    if not wg_exe:
        if not ensure_wireguard_app_installed():
            return False
        wg_exe = find_wireguard_exe()
        if not wg_exe:
            return False
    
    # For installed tunnels, use service control
    manage_without_admin = can_manage_tunnels_without_admin()
def get_config_path(tunnel_name):
    return os.path.join(get_writable_wireguard_dir(), f"{tunnel_name}.conf")
    from utils.paths import user_data_dir
    log_path = os.path.join(user_data_dir(), "vpn_debug.log")
    with open(log_path, "a") as f:
        f.write(f"start_vpn: can_manage = {manage_without_admin}, config_path_exists = {os.path.exists(config_path)}\n")
    # Allow operations to proceed even without LimitedOperatorGroup permissions
    # The system will prompt for admin privileges if needed

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
        # Allow operation to proceed - system will prompt for admin if needed
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
            import time
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
    
    # For installed tunnels, use /stop
    manage_without_admin = can_manage_tunnels_without_admin()
    config_path = get_config_path(tunnel_name)
    from utils.paths import user_data_dir
    log_path = os.path.join(user_data_dir(), "vpn_debug.log")
    with open(log_path, "a") as f:
        f.write(f"stop_vpn: can_manage = {manage_without_admin}, config_path_exists = {os.path.exists(config_path)}\n")
    # Allow operations to proceed even without LimitedOperatorGroup permissions
    # The system will prompt for admin privileges if needed

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
        # Allow operation to proceed - system will prompt for admin if needed
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
            import time
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