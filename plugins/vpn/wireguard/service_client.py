"""
IPC client for the ResistineVPN Windows service.
Authors: Merhawi 
Copyright (c) Resistine 2025
"""
import socket
import json
from utils.logger import logger

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 51888
BUFFER_SIZE = 4096
IPC_TOKEN = "RESISTINE_INTERNAL_TOKEN_CHANGE_ME"


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