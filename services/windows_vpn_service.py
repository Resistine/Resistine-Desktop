## Windows VPN Service for Resistine VPN
"""Windows Service to manage WireGuard VPN tunnels for Resistine VPN.
This service listens for IPC commands to control VPN connections.
Authors: Merhawi
"""
import win32serviceutil
import win32service
import win32event
import servicemanager

import win32con

import secrets
import socket
import threading
import json
import subprocess
import os
import logging
import time
import sys
import threading


# ---------------- Configuration ----------------

SERVICE_NAME = "ResistineVPN"
SERVICE_DISPLAY_NAME = "Resistine VPN Service"

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 51888
BUFFER_SIZE = 4096

_TOKEN_FILE = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
    "Resistine",
    "ipc_token",
)


def _init_ipc_token() -> str:
    """Load existing token or generate and persist a new one.

    The token file is written once at service startup and shared with the
    IPC client (service_client.py) so both sides use the same secret without
    it ever being hardcoded.
    """
    if os.path.exists(_TOKEN_FILE):
        try:
            with open(_TOKEN_FILE, "r") as f:
                token = f.read().strip()
            if token:
                return token
        except OSError:
            pass

    token = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
        with open(_TOKEN_FILE, "w") as f:
            f.write(token)
    except OSError as exc:
        logging.error(f"Could not persist IPC token to {_TOKEN_FILE}: {exc}")
    return token


IPC_TOKEN = _init_ipc_token()

ALLOWED_COMMANDS = {
    "status",
    "start",
    "connect",
    "disconnect",
    "stop",
    "restart",
    "health"
}


WIREGUARD_EXE = r"C:\Program Files\WireGuard\wireguard.exe"
CONFIG_BASE = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
    "Resistine",
    "wireguard"
)

os.makedirs(CONFIG_BASE, exist_ok=True)
# ---------------- Logging ----------------

TRACE = 5  # Below DEBUG (10)
logging.addLevelName(TRACE, "TRACE")

def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)

logging.Logger.trace = trace

LOG_FILE = r"C:\ProgramData\Resistine\vpn_service.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(funcName)s:%(lineno)d | %(message)s",
)
logger = logging.getLogger("ResistineVPN")


# ---------------- WireGuard helpers ----------------

def wg_service_name(tunnel):
    return f"WireGuardTunnel${tunnel}"

def find_config(tunnel: str, config_path: str = None) -> str | None:
    """
    Priority:
    1. Explicit path from GUI request (user's AppData)
    2. ProgramData (service-installed config from login/installer)
    """
    if config_path and os.path.exists(config_path):
        logger.info(f"Using provided config path: {config_path}")
        return config_path

    programdata_conf = os.path.join(CONFIG_BASE, f"{tunnel}.conf")
    if os.path.exists(programdata_conf):
        logger.info(f"Using ProgramData config: {programdata_conf}")
        return programdata_conf

    logger.warning(f"Config not found for tunnel '{tunnel}' in any known location")
    return None


def install_tunnel(tunnel, config_path=None):
    """Install a WireGuard tunnel service.
    
    Args:
        tunnel: Tunnel name.
        config_path: Full path to .conf file. If not provided,
                     falls back to CONFIG_BASE (ProgramData).
    """
    conf = find_config(tunnel, config_path)
    if not conf:
        return False, f"Config not found for tunnel: {tunnel}"

    if not os.path.exists(WIREGUARD_EXE):
        logger.error(f"WireGuard executable not found: {WIREGUARD_EXE}")
        return False, f"WireGuard not installed at {WIREGUARD_EXE}"
    # Always uninstall first to avoid duplicate tunnel services
   # uninstall_tunnel(tunnel)

    result = subprocess.run(
        [WIREGUARD_EXE, "/installtunnelservice", conf],
        capture_output=True,
        text=True,
    )

    logger.debug(f"Install result: returncode={result.returncode}")
    logger.debug(f"Install stdout: {result.stdout}")
    logger.debug(f"Install stderr: {result.stderr}")

    if "already installed" in result.stderr.lower():
        return True, "Already installed"

    if result.returncode == 0:
        logger.info(f"Tunnel '{tunnel}' installed successfully")
        time.sleep(1)
        return True, "Installed"

    logger.error(f"Failed to install tunnel '{tunnel}': {result.stderr}")
    return False, result.stderr.strip()

#############################################

def uninstall_tunnel(tunnel):
    """Remove existing WireGuard tunnel service if present."""
    svc_name = wg_service_name(tunnel)
    
    # Check if it exists first
    result = subprocess.run(
        ["sc", "query", svc_name],
        capture_output=True, text=True
    )
    if "1060" in result.stdout + result.stderr:
        return True, "Not installed"

    # Stop it first
    subprocess.run(
        ["sc", "stop", svc_name],
        capture_output=True, text=True
    )
    time.sleep(1)

    # Uninstall via WireGuard
    result = subprocess.run(
        [WIREGUARD_EXE, "/uninstalltunnelservice", tunnel],
        capture_output=True, text=True
    )
    logger.info(f"Uninstall tunnel '{tunnel}': {result.returncode}")
    time.sleep(1)
    return True, "Uninstalled"


def start_tunnel(tunnel):
    svc_name = wg_service_name(tunnel)
    logger.info(f"Starting tunnel service: {svc_name}")

    result = subprocess.run(
        ["sc", "start", svc_name],
        capture_output=True,
        text=True,
    )

    combined = (result.stdout + result.stderr).lower()

    if "already running" in combined:
        logger.info(f"Tunnel '{tunnel}' is already running")
        return True, "Already running"

    if "start_pending" in combined or result.returncode == 1056:
        logger.info(f"Tunnel '{tunnel}' is starting")
        return True, "Starting"

    if result.returncode == 0:
        logger.info(f"Tunnel '{tunnel}' started successfully")
        return True, "Started"

    logger.error(f"Failed to start tunnel '{tunnel}': {result.stderr}")
    return False, result.stderr.strip()

def stop_tunnel(tunnel):
    result = subprocess.run(
        ["sc", "stop", wg_service_name(tunnel)],
        capture_output=True,
        text=True,
    )

    out = (result.stdout + result.stderr).lower()
    if "not started" in out:
        return True, "Already stopped"

    return result.returncode == 0, out.strip()


def status_tunnel(tunnel):
    result = subprocess.run(
        ["sc", "query", wg_service_name(tunnel)],
        capture_output=True,
        text=True,
    )

    out = (result.stdout + result.stderr).lower()

    logger.trace(f"Status query for {tunnel}: returncode={result.returncode}")
    logger.trace(f"Status output: {out.strip()}")

    if "1060" in out or "does not exist" in out:
        logger.warning(f"Tunnel {tunnel} not installed")

        return "Not Installed"
    if "running" in out:
        return "Running"
    if "stopped" in out:
        return "Stopped"
    if "start_pending" in out:
        return "Starting"

    if "stop_pending" in out:
        return "Stopping"
    
    logger.warning(f"Unknown status for tunnel {tunnel}: {out.strip()}")
    return "Unknown"


# ---------------- IPC HANDLER ----------------

def handle_request(request: dict):
    if request.get("token") != IPC_TOKEN:
        return {"status": "error", "message": "Unauthorized"}

    cmd = request.get("command")
    tunnel = request.get("tunnel")
    config_path = request.get("config_path")  # <-- from GUI user's AppData

    if cmd not in ALLOWED_COMMANDS:
        return {"status": "error", "message": f"Invalid command: {cmd}"}

    if not tunnel:
        return {"status": "error", "message": "Missing tunnel"}

    try:
        if cmd == "status":
            return {"status": "ok", "state": status_tunnel(tunnel)}

        if cmd == "connect":
            state = status_tunnel(tunnel)

            if state == "Running":
                return {"status": "ok", "state": "Running", "message": "Already running"}

            if state == "Not Installed":
                ok, msg = install_tunnel(tunnel, config_path)  # <-- pass path
                if not ok:
                    return {"status": "error", "state": "Not Installed", "message": msg}

            ok, msg = start_tunnel(tunnel)
            actual_state = status_tunnel(tunnel)
            if actual_state in ("Running", "Starting"):
                return {"status": "ok", "state": actual_state, "message": msg}
            return {"status": "error", "state": actual_state, "message": msg}

        if cmd == "disconnect":
            state = status_tunnel(tunnel)
            if state in ("Stopped", "Not Installed"):
                return {"status": "ok", "state": "Stopped", "message": "Already stopped"}
            ok, msg = stop_tunnel(tunnel)
            actual_state = status_tunnel(tunnel)
            return {"status": "ok" if ok else "error", "state": actual_state, "message": msg}

        if cmd == "restart":
            stop_tunnel(tunnel)
            start_tunnel(tunnel)
            actual_state = status_tunnel(tunnel)
            return {"status": "ok", "state": actual_state, "message": "Restarted"}

        if cmd == "health":
            return {
                "status": "ok",
                "service": "running",
                "socket": "listening",
                "wireguard": status_tunnel(tunnel),
            }

        if cmd == "stop":
            stop_tunnel(tunnel)
            return {"status": "ok", "message": "Stopped"}


    except Exception as e:
        logger.exception(f"Error handling request: {e}")
        return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "Unknown command"}

# ---------------- Socket Server ----------------

def socket_server(stop_event):
    servicemanager.LogInfoMsg("Socket server thread starting")
    
    # Small delay to ensure service has fully initialized
    time.sleep(0.2)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind((SERVICE_HOST, SERVICE_PORT))
        sock.listen(5)
        sock.settimeout(1.0)
        servicemanager.LogInfoMsg(f"VPN IPC socket LISTENING on {SERVICE_HOST}:{SERVICE_PORT}")
    except Exception as e:
        servicemanager.LogErrorMsg(f"Socket bind failed: {e}")
        logger.error(f"Socket bind failed: {e}")
        return

    while True:
        rc = win32event.WaitForSingleObject(stop_event, 0)

        if rc == win32con.WAIT_OBJECT_0:
            break

        try:
            conn, _ = sock.accept()
        except socket.timeout:
            continue
        except Exception as e:
            servicemanager.LogErrorMsg(str(e))
            break

        try:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                continue

            request = json.loads(data.decode("utf-8"))
            response = handle_request(request)

            conn.sendall(json.dumps(response).encode("utf-8"))

        except Exception as e:
            conn.sendall(json.dumps({"status": "error", "message": str(e) }).encode("utf-8"))
        finally:
            conn.close()

    sock.close()
    servicemanager.LogInfoMsg("Socket server thread stopped")
def run_socket_server(stop_event):
    try:
        socket_server(stop_event)
    except Exception as e:
        servicemanager.LogErrorMsg(
            f"Socket server crashed: {repr(e)}"
        )


# ---------------- Windows Service ----------------
class ResistineVPNService(win32serviceutil.ServiceFramework):
    _svc_name_ = "ResistineVPN"
    _svc_display_name_ = "Resistine VPN Service"
    _svc_description_ = "Manages WireGuard tunnel for Resistine VPN"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)

        self.hWaitStop = win32event.CreateEvent(
            None,  
            0,     
            0,     
            None
        )
        self.worker = None

    def SvcStop(self):
        servicemanager.LogInfoMsg("ResistineVPN service stopping")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("ResistineVPN service starting")
        
        # CRITICAL: Report running status IMMEDIATELY before any blocking operations
        # Windows expects service to respond within ~30 seconds
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        servicemanager.LogInfoMsg("ResistineVPN service reported as RUNNING")

        DEFAULT_TUNNEL = "resistine_default"

        # Start IPC server first in background
        socket_thread = threading.Thread(
            target=run_socket_server,
            args=(self.hWaitStop,),
            daemon=True
        )
        socket_thread.start()
        servicemanager.LogInfoMsg("Socket server thread started")
        
        # Now do auto-start in background (non-blocking)
        # Give socket server a moment to initialize first
        time.sleep(0.5)
        
        autostart_thread = threading.Thread(
            target=self.auto_start_vpn,
            args=(DEFAULT_TUNNEL,),
            daemon=True
        )
        autostart_thread.start()
        servicemanager.LogInfoMsg("Auto-start thread started")

        # Wait for stop signal - this keeps the service alive
        servicemanager.LogInfoMsg("Service entering main loop, waiting for stop signal")
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

        # Graceful shutdown
        servicemanager.LogInfoMsg("Stop signal received, shutting down")
        try:
            stop_tunnel(DEFAULT_TUNNEL)
        except Exception as e:
            servicemanager.LogWarningMsg(f"Error stopping tunnel during shutdown: {e}")

        servicemanager.LogInfoMsg("ResistineVPN service stopped")


    def auto_start_vpn(self, tunnel):
        """Auto-start VPN in background"""
        try:
            logger.info(f"Config base directory: {CONFIG_BASE}")
            logger.info(f"WireGuard exe path: {WIREGUARD_EXE}")
            
            state = status_tunnel(tunnel)
            logger.info(f"Auto-start check: {tunnel} = {state}")

            if state in ("Not Installed", "Stopped"):
                ok, msg = install_tunnel(tunnel)
                if not ok:
                    logger.error(f"Failed to install tunnel: {msg}")
                    servicemanager.LogErrorMsg(f"Failed to install tunnel: {msg}")
                else:
                    state = status_tunnel(tunnel)
                    logger.info(f"Status after installation: {state}")
                    
                    if state != "Running":
                        ok, msg = start_tunnel(tunnel)
                        if not ok:
                            logger.error(f"Failed to start tunnel: {msg}")
                            servicemanager.LogErrorMsg(f"Failed to start tunnel: {msg}")
                        else:
                            logger.info(f"Tunnel started: {msg}")
                    else:
                        logger.info(f"Tunnel already running after installation")

        except Exception as e:
            logger.exception("Auto-start VPN failed")
            servicemanager.LogErrorMsg(f"Auto-start VPN failed: {repr(e)}")



if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(ResistineVPNService)

