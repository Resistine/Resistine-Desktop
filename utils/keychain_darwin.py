"""
macOS Keychain Utilities for Secure Key Storage
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import subprocess
import sys


def save_to_keychain(key_name, key_value, service_name="ResistineVPN"):
    """
    Save a key/value pair to macOS Keychain
    
    Args:
        key_name: Name identifier for the key (e.g., 'private_key', 'api_token')
        key_value: The actual value to store securely
        service_name: Service name in Keychain (default: 'ResistineVPN')
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Use security command to store in keychain
        subprocess.run([
            'security', 'add-generic-password',
            '-a', 'resistine-vpn-keys',  # Account name matching iOS
            '-s', service_name,
            '-w', key_value,
            '-T', '',  # No specific application access
            '-U'  # Update if exists
        ], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Keychain save failed: {e}")
        if e.stderr:
            print(f"   Error details: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"❌ Keychain save failed: {e}")
        return False


def save_wireguard_keys(private_key, public_key):
    """
    Save WireGuard keys to Keychain with iOS-compatible service names
    
    Args:
        private_key: WireGuard private key (string)
        public_key: WireGuard public key (string)
    
    Returns:
        bool: True if successful, False otherwise
    """
    # Save private key with iOS-compatible service name
    private_success = save_to_keychain(
        'private_key', 
        private_key, 
        service_name='com.resistine.wireguard.privatekey'
    )
    
    # Save public key with iOS-compatible service name
    public_success = save_to_keychain(
        'public_key', 
        public_key, 
        service_name='com.resistine.wireguard.publickey'
    )
    
    return private_success and public_success


def get_from_keychain(key_name, service_name="ResistineVPN"):
    """
    Retrieve a key/value pair from macOS Keychain
    
    Args:
        key_name: Name identifier for the key (e.g., 'private_key', 'api_token')
        service_name: Service name in Keychain (default: 'ResistineVPN')
    
    Returns:
        str: The stored value, or None if not found
    """
    try:
        result = subprocess.check_output([
            'security', 'find-generic-password',
            '-a', 'resistine-vpn-keys',  # Account name matching iOS
            '-s', service_name,
            '-w'
        ], text=True, stderr=subprocess.DEVNULL).strip()
        return result if result else None
    except subprocess.CalledProcessError:
        # Key not found in keychain
        return None
    except Exception as e:
        print(f"❌ Keychain retrieval failed: {e}")
        return None


def get_wireguard_private_key():
    """Get WireGuard private key from Keychain"""
    return get_from_keychain('private_key', service_name='com.resistine.wireguard.privatekey')


def get_wireguard_public_key():
    """Get WireGuard public key from Keychain"""
    return get_from_keychain('public_key', service_name='com.resistine.wireguard.publickey')


def delete_from_keychain(key_name, service_name="ResistineVPN"):
    """
    Delete a key/value pair from macOS Keychain
    
    Args:
        key_name: Name identifier for the key to delete
        service_name: Service name in Keychain (default: 'ResistineVPN')
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        subprocess.run([
            'security', 'delete-generic-password',
            '-a', 'resistine-vpn-keys',  # Account name matching iOS
            '-s', service_name
        ], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        # Key doesn't exist, which is fine
        return True
    except Exception as e:
        print(f"❌ Keychain deletion failed: {e}")
        return False


def delete_wireguard_keys():
    """
    Delete WireGuard keys from Keychain (for key regeneration)
    
    Returns:
        bool: True if successful, False otherwise
    """
    private_deleted = delete_from_keychain('private_key', service_name='com.resistine.wireguard.privatekey')
    public_deleted = delete_from_keychain('public_key', service_name='com.resistine.wireguard.publickey')
    return private_deleted and public_deleted


def key_exists_in_keychain(key_name, service_name="ResistineVPN"):
    """
    Check if a key exists in macOS Keychain
    
    Args:
        key_name: Name identifier for the key to check
        service_name: Service name in Keychain (default: 'ResistineVPN')
    
    Returns:
        bool: True if key exists, False otherwise
    """
    try:
        subprocess.check_output([
            'security', 'find-generic-password',
            '-a', 'resistine-vpn-keys',  # Account name matching iOS
            '-s', service_name,
            '-w'
        ], stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


def wireguard_keys_exist():
    """Check if WireGuard keys exist in Keychain"""
    private_exists = key_exists_in_keychain('private_key', service_name='com.resistine.wireguard.privatekey')
    public_exists = key_exists_in_keychain('public_key', service_name='com.resistine.wireguard.publickey')
    return private_exists and public_exists

