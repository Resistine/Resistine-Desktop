# plugins/vpn/wireguard/service_client.py
"""IPC client for communicating with the ResistineVPN Windows service."""
import socket
import json

from utils.logger import logger

HOST = "127.0.0.1"
PORT = 51888

IPC_TOKEN = "RESISTINE_INTERNAL_TOKEN_CHANGE_ME"


def send_command(command, tunnel):
    """Send a command to the VPN service via IPC socket.

    Returns a dict with at least a 'status' key.
    On connection failure returns an error dict with state='Stopped'.
    """
    payload = {
        "token": IPC_TOKEN,
        "command": command,
        "tunnel": tunnel
    }

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((HOST, PORT))
            s.send(json.dumps(payload).encode())
            return json.loads(s.recv(4096).decode())
    except ConnectionRefusedError:
        logger.warning("VPN service is not running (connection refused)")
        return {"status": "error", "state": "Stopped", "message": "VPN service not running"}
    except socket.timeout:
        logger.warning("VPN service timed out")
        return {"status": "error", "state": "Stopped", "message": "VPN service timed out"}
    except Exception as e:
        logger.error(f"IPC communication failed: {e}")
        return {"status": "error", "state": "Stopped", "message": str(e)}
