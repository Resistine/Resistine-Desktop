import os
import json
import platform
import logging
from utils.encryption import encrypt_data, decrypt_data, get_or_create_key

logger = logging.getLogger(__name__)

# User directories
HOME_DIR = os.path.expanduser("~")

# Platform identifiers
PLATFORM_DARWIN = "Darwin"
PLATFORM_LINUX = "Linux"
PLATFORM_WINDOWS = "Windows"

# Application names
APP_NAME = "Resistine"
APP_NAME_LOWER = "resistine"

# macOS path components
MACOS_LIBRARY = "Library"
MACOS_APP_SUPPORT = "Application Support"

# Linux path components
LINUX_CONFIG_DIR = ".config"

# Fallback directory
FALLBACK_DIR = ".resistine"
# Configuration files
LOGIN_STATE_FILE = "login.json"

# Environment variables
WINDOWS_APPDATA_ENV = 'APPDATA'

# JSON keys
KEY_LOGGED_IN = "logged_in"
KEY_EMAIL = "email"
KEY_OPENAI_API_KEY = "openai_api_key"

# Error messages
ERR_UNSUPPORTED_PLATFORM = "Unsupported platform"

def get_config_dir():
    """Get the configuration directory based on the platform."""
    if platform.system() == PLATFORM_DARWIN:
        return os.path.join(HOME_DIR, MACOS_LIBRARY, MACOS_APP_SUPPORT, APP_NAME)
    elif platform.system() == PLATFORM_LINUX:
        return os.path.join(HOME_DIR, LINUX_CONFIG_DIR, APP_NAME_LOWER)
    elif platform.system() == PLATFORM_WINDOWS:
        appdata_dir = os.environ.get(WINDOWS_APPDATA_ENV, HOME_DIR)
        return os.path.join(appdata_dir, APP_NAME)
    else:
        # Fallback for other systems
        return os.path.join(HOME_DIR, FALLBACK_DIR)
# Subdirectory names

        

def get_login_state_file():
    """Get the path to the login state file."""
    config_dir = get_config_dir()
    return os.path.join(config_dir, LOGIN_STATE_FILE)

def save_login_state(email):
    """Save the login state to a file."""
    try:
        config_dir = get_config_dir()
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        state_file = get_login_state_file()
        data = {
            KEY_LOGGED_IN: True,
            KEY_EMAIL: email
        }
        
        with open(state_file, 'w') as f:
            json.dump(data, f)
        
        logger.info(f"Login state saved to {state_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save login state: {e}")
        return False

def is_logged_in():
    """Check if the user is logged in."""
    try:
        state_file = get_login_state_file()
        if not os.path.exists(state_file):
            return False
        
        with open(state_file, 'r') as f:
            data = json.load(f)
            
        return data.get(KEY_LOGGED_IN, False)
    except Exception as e:
        logger.error(f"Failed to check login state: {e}")
        return False

def clear_login_state():
    """Clear the login state (logout)."""
    try:
        state_file = get_login_state_file()
        if os.path.exists(state_file):
            os.remove(state_file)
            logger.info("Login state cleared")
        return True
    except Exception as e:
        logger.error(f"Failed to clear login state: {e}")
        return False





# OpenAI API Key Management ###############################################################################

def save_openai_api_key(api_key):
    """
    Save the OpenAI API key securely using the encryption module.
    The key is stored in the system keyring (encrypted).
    
    :param api_key: The OpenAI API key to save
    :return: True if successful, False otherwise
    """
    try:
        # Ensure encryption key exists
        get_or_create_key()
        
        # Encrypt and store the API key
        encrypted_data = encrypt_data({KEY_OPENAI_API_KEY: api_key})
        
        logger.info("OpenAI API key saved securely")
        return True
    except Exception as e:
        logger.error(f"Failed to save OpenAI API key: {e}")
        return False


def get_openai_api_key():
    """
    Retrieve the OpenAI API key from secure storage.
    
    :return: The API key string, or None if not found or on error
    """
    try:
        decrypted_data = decrypt_data()
        api_key = decrypted_data.get(KEY_OPENAI_API_KEY)
        
        if api_key:
            logger.info("OpenAI API key retrieved successfully")
        else:
            logger.warning("OpenAI API key not found in encrypted data")
        
        return api_key
    except ValueError as e:
        # No encrypted data found
        logger.info("No OpenAI API key configured yet")
        return None
    except Exception as e:
        logger.error(f"Failed to retrieve OpenAI API key: {e}")
        return None


def has_openai_api_key():
    """
    Check if an OpenAI API key is configured.
    
    :return: True if API key exists, False otherwise
    """
    api_key = get_openai_api_key()
    return api_key is not None and api_key.strip() != ""
