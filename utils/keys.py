import os
import base64
from typing import Optional, Tuple
import platform
import keyring
from nacl.public import PrivateKey  # X25519 (WireGuard-compatible)

_SERVICE = "ResistineAI"
_PRIV_KEY_ACCOUNT = "wireguard_private_key_b64"
_UTILS_DIR = os.path.dirname(os.path.realpath(__file__))
_PUB_KEY_PATH = os.path.join(_UTILS_DIR, "wireguard_public.key")

def get_writable_wireguard_dir() -> str:
    """Return per-user writable folder for WireGuard configs."""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        wg_dir = os.path.join(base, "Resistine AI", "wireguard")
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
        wg_dir = os.path.join(base, "Resistine AI", "wireguard")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        wg_dir = os.path.join(base, "resistine-ai", "wireguard")
    os.makedirs(wg_dir, exist_ok=True)
    return wg_dir

def _generate_keypair_b64() -> Tuple[str, str]:
    """Return (private_b64, public_b64)."""
    priv = PrivateKey.generate()
    priv_b = priv.encode()
    pub_b = priv.public_key.encode()
    return base64.b64encode(priv_b).decode("ascii"), base64.b64encode(pub_b).decode("ascii")

def ensure_keys_exist() -> None:
    """Generate keypair on first run. Private key -> OS keychain; public key -> file."""
    os.makedirs(_UTILS_DIR, exist_ok=True)
    existing_priv_b64 = keyring.get_password(_SERVICE, _PRIV_KEY_ACCOUNT)
    if not existing_priv_b64:
        priv_b64, pub_b64 = _generate_keypair_b64()
        keyring.set_password(_SERVICE, _PRIV_KEY_ACCOUNT, priv_b64)
        with open(_PUB_KEY_PATH, "w", encoding="utf-8") as f:
            f.write(pub_b64)
    else:
        # Ensure public key file exists
        if not os.path.exists(_PUB_KEY_PATH):
            try:
                priv_b = base64.b64decode(existing_priv_b64)
                pub_b64 = base64.b64encode(PrivateKey(priv_b).public_key.encode()).decode("ascii")
                with open(_PUB_KEY_PATH, "w", encoding="utf-8") as f:
                    f.write(pub_b64)
            except Exception:
                pass

def load_public_key() -> Optional[str]:
    try:
        with open(_PUB_KEY_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def load_private_key_b64() -> Optional[str]:
    return keyring.get_password(_SERVICE, _PRIV_KEY_ACCOUNT)

def write_demo_config_if_absent() -> Optional[str]:
    """Create a demo WireGuard config once, substituting the generated private key."""
    wg_dir = get_writable_wireguard_dir()
    demo_path = os.path.join(wg_dir, "demo.conf")
    if os.path.exists(demo_path):
        return demo_path

    priv_b64 = load_private_key_b64()
    if not priv_b64:
        return None

    server_pub_placeholder = "SERVER_PUBLIC_KEY_HERE"
    endpoint_placeholder = "vpn.example.org:51820"

    content = f"""# Demo WireGuard config (example)
# Replace Endpoint and Peer PublicKey with values from your VPN provider.
# The PrivateKey below was generated automatically for this user.

[Interface]
PrivateKey = {priv_b64}
Address = 10.0.0.2/32
DNS = 1.1.1.1

[Peer]
PublicKey = {server_pub_placeholder}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint_placeholder}
PersistentKeepalive = 25
"""
    with open(demo_path, "w", encoding="utf-8") as f:
        f.write(content)
    return demo_path