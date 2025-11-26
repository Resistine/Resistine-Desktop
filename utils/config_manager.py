import os
import json
import platform
import logging

logger = logging.getLogger(__name__)

def get_config_dir():
    """Get the configuration directory based on the platform."""
    if platform.system() == "Darwin":
        home_dir = os.path.expanduser("~")
        return os.path.join(home_dir, "Library", "Application Support", "Resistine")
    elif platform.system() == "Linux":
        home_dir = os.path.expanduser("~")
        return os.path.join(home_dir, ".config", "resistine")
    elif platform.system() == "Windows":
        appdata_dir = os.environ.get('APPDATA', os.path.expanduser("~"))
        return os.path.join(appdata_dir, "Resistine")
    else:
        # Fallback for other systems
        return os.path.join(os.path.expanduser("~"), ".resistine")

def get_login_state_file():
    """Get the path to the login state file."""
    config_dir = get_config_dir()
    return os.path.join(config_dir, "login.json")

def save_login_state(email):
    """Save the login state to a file."""
    try:
        config_dir = get_config_dir()
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        
        state_file = get_login_state_file()
        data = {
            "logged_in": True,
            "email": email
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
            
        return data.get("logged_in", False)
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
