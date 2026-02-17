# plugins/vpn/wireguard/service_client.py
import socket
import json

HOST = "127.0.0.1"
PORT = 51888

IPC_TOKEN = "RESISTINE_INTERNAL_TOKEN_CHANGE_ME"

def send_command(command, tunnel):
    payload = {
        "token": IPC_TOKEN,
        "command": command,
        "tunnel": tunnel
    }

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.send(json.dumps(payload).encode())
        return json.loads(s.recv(4096).decode())
