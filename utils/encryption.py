"""
This script is used to encrypt and decrypt data using the Fernet symmetric encryption algorithm.
It securely stores the encryption key using the keyring module ONLY if a secure backend is available.
The encrypted data is stored in a dictionary format and can be retrieved later.

Author: Peres J. and the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from cryptography.fernet import Fernet
import keyring
import json
from utils.i18n import get_text


class InsecureKeyringuException(Exception):
    """Raised when the keyring backend is not secure enough for credential storage."""
    pass


def is_keyring_secure():
    """
    Check if the current keyring backend is secure.
    
    Insecure backends include:
    - PlaintextKeyring (stores passwords in plaintext)
    - Null/Fail backends
    - EncryptedKeyring (uses a master password that may be stored insecurely)
    
    Secure backends include:
    - SecretService.Keyring (GNOME Keyring on Linux)
    - Keychain (macOS)
    - WinVaultKeyring (Windows Credential Locker)
    
    :return: True if secure, False otherwise
    :raises InsecureKeyringuException: If the backend is insecure with instructions
    """
    backend = keyring.get_keyring()
    backend_name = backend.__class__.__name__
    backend_module = backend.__class__.__module__
    backend_full_path = f"{backend_module}.{backend_name}"
    
    # List of known insecure backend modules/paths
    insecure_backend_patterns = [
        'keyring.backends.fail',
        'keyring.backends.null',
        'keyring.backends.PlaintextKeyring',
        'keyring.backends.EncryptedKeyring',
    ]
    
    # Check if backend matches any insecure pattern
    for pattern in insecure_backend_patterns:
        if pattern.lower() in backend_full_path.lower():
            raise InsecureKeyringuException(
                get_text('encryption.insecure_backend', 
                        backend=backend_full_path)
            )
    
    return True


def get_or_create_key():
    """
    Retrieve or generate an encryption key and store it securely in the system keyring.
    
    :return: The encryption key as bytes.
    :raises InsecureKeyringuException: If no secure keyring backend is available
    """
    # Check if keyring backend is secure first
    is_keyring_secure()
    
    key = keyring.get_password("resistine", "encryption_key")
    if key is None:
        key_bytes = Fernet.generate_key()
        keyring.set_password("resistine", "encryption_key", key_bytes.decode())
        print(get_text('encryption.key_stored_keyring'))
        return key_bytes
    else:
        print(get_text('encryption.key_retrieved_keyring'))
        return key.encode()


def retrieve_key():
    """
    Retrieve the stored encryption key from the system keyring.
    
    :return: The encryption key as bytes.
    :raises ValueError: If no key is found in keyring.
    :raises InsecureKeyringuException: If no secure keyring backend is available
    """
    # Check if keyring backend is secure first
    is_keyring_secure()
    
    key = keyring.get_password("resistine", "encryption_key")
    if key is None:
        raise ValueError(get_text('encryption.no_key_found'))
    return key.encode()


def encrypt_data(data_dict):
    """
    Encrypt the data in the provided dictionary and store it securely in the system keyring.
    
    :param data_dict: A dictionary containing the data to be encrypted.
    :return: A dictionary containing the encrypted data.
    :raises InsecureKeyringuException: If no secure keyring backend is available
    """
    # Check if keyring backend is secure first
    is_keyring_secure()
    
    key = retrieve_key()
    cipher = Fernet(key)
    encrypted_data_dict = {}

    for key_name, value in data_dict.items():
        if isinstance(value, bytes):
            encrypted_data_dict[key_name] = cipher.encrypt(value).decode()
        else:
            encrypted_data_dict[key_name] = cipher.encrypt(str(value).encode()).decode()

    keyring.set_password("resistine", "encrypted_data", json.dumps(encrypted_data_dict))
    print(get_text('encryption.data_stored_keyring'))
    
    return encrypted_data_dict


def decrypt_data():
    """
    Decrypt the stored encrypted data from the system keyring.
    
    :return: A dictionary containing the decrypted data.
    :raises ValueError: If no encrypted data is found in keyring.
    :raises InsecureKeyringuException: If no secure keyring backend is available
    """
    # Check if keyring backend is secure first
    is_keyring_secure()
    
    key = retrieve_key()
    cipher = Fernet(key)

    encrypted_data = keyring.get_password("resistine", "encrypted_data")
    if encrypted_data is None:
        raise ValueError(get_text('encryption.no_data_found'))
    
    encrypted_data_dict = json.loads(encrypted_data)
    decrypted_data_dict = {}
    
    for key_name, value in encrypted_data_dict.items():
        decrypted_data_dict[key_name] = cipher.decrypt(value.encode()).decode()

    return decrypted_data_dict
