"""
This script is used to encrypt and decrypt data using the Fernet symmetric encryption algorithm.
It securely stores the encryption key using the keyring module or a local file.
The encrypted data is stored in a dictionary format and can be retrieved later.
Author: Peres J.
Copyright (c) Resistine 2025
Licensed under the Apache License 2.0
"""

from cryptography.fernet import Fernet
import keyring
import os
import platform
import json


# Identify the system
def identify_system():
    """
    Identify the operating system and return a string representing the system type.
    
    :return: A string representing the system type ('linux', 'windows', 'mac', 'wsl', or 'unknown').
    """
    system_platform = platform.system().lower()

    if system_platform == "linux":
        if "microsoft" in platform.uname().release.lower():
            return "wsl"  # Windows Subsystem for Linux
        return "linux"
    elif system_platform == "windows":
        return "windows"
    elif system_platform == "darwin":
        return "mac"
    else:
        return "unknown"

# Determine where to store the key according to the system
def get_key_storage_path():
    """
    Determine the storage path for the encryption key based on the operating system.
    
    :return: A string representing the storage path or 'keyring' if using keyring for storage.
    """
    system_type = identify_system()

    if system_type == "wsl":
        # Store in the virtual environment directory
        return os.path.expanduser("~/.config/resistine/keyfile.enc")
    else:
        # Use keyring for Linux, Mac, and Windows
        return "keyring"

# Get or create a key and store it securely
def get_or_create_key():
    """
    Retrieve or generate an encryption key and store it securely.
    
    :return: The encryption key as bytes.
    """
    storage_path = get_key_storage_path()

    if storage_path == "keyring":
        key = keyring.get_password("resistine", "encryption_key")
        if key is None:
            key = Fernet.generate_key()
            keyring.set_password("resistine", "encryption_key", key.decode())
            print("Key securely stored in keyring.")
        else:
            print("Key retrieved from keyring.")
        return key.encode()
    else:
        if os.path.exists(storage_path):
            with open(storage_path, "rb") as file:
                key = file.read()
            print(f"Key retrieved from: {storage_path}")
        else:
            key = Fernet.generate_key()
            os.makedirs(os.path.dirname(storage_path), exist_ok=True)
            with open(storage_path, "wb") as file:
                file.write(key)
            print(f"Key securely stored in: {storage_path}")
        return key

# Retrieve the stored key
def retrieve_key():
    """
    Retrieve the stored encryption key.
    
    :return: The encryption key as bytes.
    :raises ValueError: If no key is found in keyring.
    :raises FileNotFoundError: If the key file is not found.
    """
    storage_path = get_key_storage_path()

    if storage_path == "keyring":
        key = keyring.get_password("resistine", "encryption_key")
        if key is None:
            raise ValueError("No key found in keyring. Generate a key first.")
        return key.encode()
    else:
        with open(storage_path, "rb") as file:
            return file.read()

# Encrypt data in a dictionary
def encrypt_data(data_dict):
    """
    Encrypt the data in the provided dictionary.
    
    :param data_dict: A dictionary containing the data to be encrypted.
    :return: A dictionary containing the encrypted data.
    """
    key = retrieve_key()
    cipher = Fernet(key)
    encrypted_data_dict = {}

    for key, value in data_dict.items():
        encrypted_data_dict[key] = cipher.encrypt(value.encode()).decode()

    storage_path = get_key_storage_path()

    if storage_path == "keyring":
        keyring.set_password("resistine", "encrypted_data", json.dumps(encrypted_data_dict))
        print("Encrypted data securely stored in keyring.")
    else:
        encrypted_data_path = os.path.expanduser("~/.config/resistine/encrypted_data.enc")
        os.makedirs(os.path.dirname(encrypted_data_path), exist_ok=True)
        with open(encrypted_data_path, "w") as file:
            json.dump(encrypted_data_dict, file)
        print(f"Encrypted data stored in: {encrypted_data_path}")
    return encrypted_data_dict

# Data to decrypt
def decrypt_data():
    """
    Decrypt the stored encrypted data.
    
    :return: A dictionary containing the decrypted data.
    :raises ValueError: If no encrypted data is found in keyring.
    :raises FileNotFoundError: If the encrypted data file is not found.
    """
    key = retrieve_key()
    cipher = Fernet(key)

    storage_path = get_key_storage_path()

    if storage_path == "keyring":
        encrypted_data = keyring.get_password("resistine", "encrypted_data")
        if encrypted_data is None:
            raise ValueError("No encrypted data found in keyring.")
        encrypted_data_dict = json.loads(encrypted_data)
    else:
        encrypted_data_path = os.path.expanduser("~/.config/resistine/encrypted_data.enc")
        if not os.path.exists(encrypted_data_path):
            raise FileNotFoundError("Encrypted data file not found.")
        with open(encrypted_data_path, "r") as file:
            encrypted_data_dict = json.load(file)

    decrypted_data_dict = {}
    for key, value in encrypted_data_dict.items():
        decrypted_data_dict[key] = cipher.decrypt(value.encode()).decode()

    return decrypted_data_dict
