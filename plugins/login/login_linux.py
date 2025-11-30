# -*- coding: utf-8 -*-
# @file plugins/login/login_linux.py
# @namespace plugins.login.login_linux
# Description: Linux-specific implementation for WireGuard VPN key management and configuration saving.

# Author: Petr and the Resistine Team
# Copyright: Resistine (c) 2025
# Licensed under the GNU General Public License v2 or later

import logging
import json
import os
import sys

# Add project root to path to ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from plugins.vpn.wireguard import vpn_functions_linux as vpn_funcs

logger = logging.getLogger(__name__)

def setup_vpn_keys():
    """
    Generate and save new WireGuard keys for the session.
    Returns the public key if successful, None otherwise.
    """
    try:
        # Step 1: Regenerate fresh keys for this sign-in session
        # Delete old keys (if they exist) to ensure fresh key pair
        logger.debug("Regenerating WireGuard keys for new login session")
        vpn_funcs.delete_wireguard_keys()
        
        # Generate new key pair
        keys = vpn_funcs.generate_wireguard_keys()
        if not keys:
            logger.error("Failed to generate keys")
            return None
        
        # Save both private and public keys
        if not vpn_funcs.save_wireguard_keys(keys['private_key'], keys['public_key']):
            logger.error("Failed to save keys securely")
            return None
        
        # Get public key for API transmission
        public_key = keys['public_key']
        
        if not public_key:
            logger.error("Failed to get public key")
            return None
            
        logger.debug(f"WireGuard Public Key Validated: Length={len(public_key)} characters")
        return public_key

    except Exception as e:
        logger.error(f"Error setting up VPN keys: {e}")
        return None

def save_vpn_configuration(vpn_config_json):
    """
    Parse and save the VPN configuration.
    Returns the path to the saved config file if successful, None otherwise.
    """
    try:
        if not vpn_config_json:
            return None
            
        logger.debug("WireGuard config received from API")
        
        # Log redacted config for debugging
        try:
            vpn_config = json.loads(vpn_config_json) if isinstance(vpn_config_json, str) else vpn_config_json
            safe_config = {}
            if "Interface" in vpn_config:
                safe_config["Interface"] = {
                    "Address": vpn_config["Interface"].get("Address", ""),
                    "DNS": vpn_config["Interface"].get("DNS", []),
                    "PrivateKey": "[REDACTED]" if vpn_config["Interface"].get("PrivateKey") else None
                }
            if "Peer" in vpn_config:
                safe_config["Peer"] = {
                    "PublicKey": "[REDACTED]" if vpn_config["Peer"].get("PublicKey") else None,
                    "AllowedIPs": vpn_config["Peer"].get("AllowedIPs", []),
                    "Endpoint": vpn_config["Peer"].get("Endpoint", "")
                }
            logger.debug(f"VPN Config (redacted): {json.dumps(safe_config)}")
        except Exception as e:
            logger.debug(f"Error parsing VPN config for logging: {e}")

        # Create config file
        config_path = vpn_funcs.parse_and_create_vpn_config(vpn_config_json, config_name="wg0")
        
        if config_path:
            logger.info("VPN configuration saved successfully")
            return config_path
        else:
            logger.warning("Failed to create VPN config")
            return None
            
    except Exception as e:
        logger.warning(f"Error creating VPN config: {e}")
        return None
