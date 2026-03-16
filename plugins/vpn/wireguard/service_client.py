"""
IPC client for the ResistineVPN Windows service.
Authors: Merhawi
Copyright (c) Resistine 2025
"""
import os
import socket
import json
from utils.logger import logger


SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 51888
BUFFER_SIZE = 4096

# Path to the token file written by the service at startup.
# Both service and client read from this location so the token is never
# hardcoded and is unique per installation.
_TOKEN_FILE = os.path.join(
    os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
    "Resistine",
    "ipc_token",
)


def _load_ipc_token() -> str:
    """Load the IPC token from the shared token file or environment variable."""
    if os.path.exists(_TOKEN_FILE):
        try:
            with open(_TOKEN_FILE, "r") as f:
                token = f.read().strip()
            if token:
                return token
        except OSError:
            pass
    # Fallback: allow override via environment (useful for CI / testing)
    return os.environ.get("RESISTINE_IPC_TOKEN", "")


IPC_TOKEN = _load_ipc_token()


def send_command(command: str, tunnel: str, config_path: str = None) -> dict:
    """Send a command to the ResistineVPN service via IPC socket.

    Args:
        command: The command to send (status, connect, disconnect, etc.)
        tunnel: The tunnel name.
        config_path: Full path to the .conf file (optional, used for connect).
    Returns:
        dict with at minimum 'status' key.
    """
    payload = {
        "token": IPC_TOKEN,
        "command": command,
        "tunnel": tunnel,
    }
    if config_path:
        payload["config_path"] = config_path

    print(f"Sending command to VPN service: {command} for tunnel: {tunnel}")
    if config_path:
        print(f"Config path: {config_path}")

    #  initialise sock before the try block so the finally
    # clause never hits an unbound name if socket.socket() itself raises.
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((SERVICE_HOST, SERVICE_PORT))
        sock.sendall(json.dumps(payload).encode("utf-8"))

        data = sock.recv(BUFFER_SIZE)
        response = json.loads(data.decode("utf-8"))
        logger.debug(f"Service response for '{command}': {response}")
        return response

    except ConnectionRefusedError:
        logger.error("VPN service is not running (connection refused)")
        return {"status": "error", "state": "Stopped", "message": "VPN service not running"}
    except socket.timeout:
        logger.error("VPN service timed out")
        return {"status": "error", "state": "Stopped", "message": "VPN service timed out"}
    except Exception as e:
        logger.exception("Unexpected error communicating with VPN service")
        return {"status": "error", "state": "Stopped", "message": str(e)}
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
