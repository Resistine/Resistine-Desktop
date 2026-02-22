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

IPC_TOKEN = "RESISTINE_INTERNAL_TOKEN_CHANGE_ME"

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


def install_tunnel(tunnel):
    conf = os.path.join(CONFIG_BASE, f"{tunnel}.conf")
    logger.info(f"Installing tunnel '{tunnel}' from: {conf}")
    
    if not os.path.exists(conf):
        logger.error(f"Config file not found: {conf}")
        logger.info(f"Available files in {CONFIG_BASE}: {os.listdir(CONFIG_BASE) if os.path.exists(CONFIG_BASE) else 'directory does not exist'}")
        return False, f"Config not found: {conf}"

    if not os.path.exists(WIREGUARD_EXE):
        logger.error(f"WireGuard executable not found: {WIREGUARD_EXE}")
        return False, f"WireGuard not installed at {WIREGUARD_EXE}"

    result = subprocess.run(
        [WIREGUARD_EXE, "/installtunnelservice", conf],
        capture_output=True,
        text=True,
    )

    logger.debug(f"WireGuard install result - returncode: {result.returncode}")
    logger.debug(f"WireGuard install stdout: {result.stdout}")
    logger.debug(f"WireGuard install stderr: {result.stderr}")

    if "already installed" in result.stderr.lower():
        return True, "Already installed"

    if result.returncode == 0:
        logger.info(f"Tunnel '{tunnel}' installed successfully")
        # Give WireGuard a moment to initialize the service
        time.sleep(1)
    else:
        logger.error(f"Failed to install tunnel '{tunnel}': {result.stderr}")

    return result.returncode == 0, result.stderr.strip()




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

    # ---- Security: token required ----
    token = request.get("token")
    if token != IPC_TOKEN:
        return {
            "status": "error",
            "message": "Unauthorized"
        }
    cmd = request.get("command")
    tunnel = request.get("tunnel")
    if cmd not in ALLOWED_COMMANDS:
        return {
            "status": "error",
            "message": f"Invalid command: {cmd}"
        }
    try:

        if not tunnel:
            return {"status": "error", "message": "Missing tunnel"}

        if cmd == "status":
            return {"status": "ok", "state": status_tunnel(tunnel)}

        if cmd == "connect":
            state = status_tunnel(tunnel)

            if state == "Running":
                return {"status": "ok", "message": "Already running"}

            if state == "Not Installed":
                ok, msg = install_tunnel(tunnel)
                if not ok:
                    return {"status": "error", "message": msg}
                
            ok, msg = start_tunnel(tunnel)
            return {"status": "ok" if ok else "error", "message": msg}
        
        if cmd == "connect":
            state = status_tunnel(tunnel)

            if state == "Running":
                return {"status": "ok", "state": "Running", "message": "Already running"}

            if state == "Not Installed":
                ok, msg = install_tunnel(tunnel)
                if not ok:
                    return {"status": "error", "state": "Not Installed", "message": msg}

            ok, msg = start_tunnel(tunnel)
            # Re-query actual state after start attempt
            actual_state = status_tunnel(tunnel)
            if actual_state in ("Running", "Starting"):
                return {"status": "ok", "state": actual_state, "message": msg}
            return {"status": "error", "state": actual_state, "message": msg}

        if cmd == "disconnect":
            state = status_tunnel(tunnel)

            if state in ("Stopped", "Not Installed"):
                return {"status": "ok", "message": "Already stopped"}
            
            ok, msg = stop_tunnel(tunnel)
            return {"status": "ok" if ok else "error", "message": msg}
        
        if cmd == "start":
            start_tunnel(tunnel)
            return {"status": "ok", "message": "Started"}

        if cmd == "stop":
            stop_tunnel(tunnel)
            return {"status": "ok", "message": "Stopped"}


        if cmd == "restart":
            stop_tunnel(tunnel)
            start_tunnel(tunnel)
            return {"status": "ok", "message": "Restarted"}

        if cmd == "health":
            return {
                "status": "ok",
                "service": "running",
                "socket": "listening",
                "wireguard": status_tunnel(tunnel)
            }

        
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

