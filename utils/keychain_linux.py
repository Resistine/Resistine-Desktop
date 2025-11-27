"""
Linux Keychain Utilities for Secure Key Storage
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

KEYS_FILE_PATH = os.path.expanduser("~/.config/resistine/keys.json")

def _ensure_keys_file():
    """Ensure the keys file and directory exist with secure permissions."""
    directory = os.path.dirname(KEYS_FILE_PATH)
    if not os.path.exists(directory):
        os.makedirs(directory, mode=0o700)
    
    if not os.path.exists(KEYS_FILE_PATH):
        with open(KEYS_FILE_PATH, 'w') as f:
            json.dump({}, f)
        os.chmod(KEYS_FILE_PATH, 0o600)

def _load_keys():
    """Load keys from the JSON file."""
    _ensure_keys_file()
    try:
        with open(KEYS_FILE_PATH, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("Failed to decode keys file. Resetting.")
        return {}
    except Exception as e:
        logger.error(f"Error loading keys: {e}")
        return {}

def _save_keys(keys):
    """Save keys to the JSON file."""
    _ensure_keys_file()
    try:
        with open(KEYS_FILE_PATH, 'w') as f:
            json.dump(keys, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving keys: {e}")
        return False

def save_to_keychain(key_name, key_value, service_name="ResistineVPN"):
    """
    Save a key/value pair to the secure JSON file.
    
    Args:
        key_name: Name identifier for the key
        key_value: The actual value to store
        service_name: Service name (used as a namespace)
    
    Returns:
        bool: True if successful, False otherwise
    """
    keys = _load_keys()
    if service_name not in keys:
        keys[service_name] = {}
    
    keys[service_name][key_name] = key_value
    return _save_keys(keys)

def get_from_keychain(key_name, service_name="ResistineVPN"):
    """
    Retrieve a key/value pair from the secure JSON file.
    
    Args:
        key_name: Name identifier for the key
        service_name: Service name
    
    Returns:
        str: The stored value, or None if not found
    """
    keys = _load_keys()
    return keys.get(service_name, {}).get(key_name)

def delete_from_keychain(key_name, service_name="ResistineVPN"):
    """
    Delete a key/value pair from the secure JSON file.
    
    Args:
        key_name: Name identifier for the key
        service_name: Service name
    
    Returns:
        bool: True if successful (or didn't exist), False otherwise
    """
    keys = _load_keys()
    if service_name in keys and key_name in keys[service_name]:
        del keys[service_name][key_name]
        return _save_keys(keys)
    return True

def save_wireguard_keys(private_key, public_key):
    """
    Save WireGuard keys.
    
    Args:
        private_key: WireGuard private key
        public_key: WireGuard public key
    
    Returns:
        bool: True if successful
    """
    # Using the same service names as Darwin for consistency in logic, 
    # though strictly speaking they are just JSON keys here.
    p1 = save_to_keychain('private_key', private_key, service_name='com.resistine.wireguard.privatekey')
    p2 = save_to_keychain('public_key', public_key, service_name='com.resistine.wireguard.publickey')
    return p1 and p2

def get_wireguard_private_key():
    """Get WireGuard private key."""
    return get_from_keychain('private_key', service_name='com.resistine.wireguard.privatekey')

def get_wireguard_public_key():
    """Get WireGuard public key."""
    return get_from_keychain('public_key', service_name='com.resistine.wireguard.publickey')

def delete_wireguard_keys():
    """Delete WireGuard keys."""
    d1 = delete_from_keychain('private_key', service_name='com.resistine.wireguard.privatekey')
    d2 = delete_from_keychain('public_key', service_name='com.resistine.wireguard.publickey')
    return d1 and d2
