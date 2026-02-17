
from plugins.vpn.wireguard.service_client import send_command

DEFAULT_TUNNEL = "resistine_vpn"

def get_status():
    return send_command("status", DEFAULT_TUNNEL)

def connect():
    return send_command("connect", DEFAULT_TUNNEL)

def disconnect():
    return send_command("disconnect", DEFAULT_TUNNEL)

def toggle():
    status = get_status()
    if status["state"] == "Running":
        return disconnect()
    return connect()
