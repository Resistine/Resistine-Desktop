# TODO: Remove host_url and vpn_name parameters and get them from tha API instead!!!
# TODO: Remove private_key and IP parameters and get it from the API instead!!!
# TODO: Create tests.
# TODO: Create documentation.

import requests
import logging
import json

logger = logging.getLogger(__name__)

class LoginAPI:
    def __init__(self, base_url):
        self.base_url = base_url

    def send_otp(self, email):
        """
        Send OTP to the specified email.
        Returns a tuple (success, message, data).
        """
        try:
            api_url = f"{self.base_url}/send-otp"
            payload = {"email": email}
            
            logger.debug(f"Sending OTP to {email}")
            response = requests.post(api_url, json=payload, timeout=90)
            
            if response.ok:
                try:
                    result = response.json()
                    message = result.get("message", "")
                    status = result.get("status", "").lower()
                    
                    if status in ["error", "failed", "failure"]:
                        error_msg = message or result.get("error", "Failed to send OTP")
                        return False, error_msg, result
                    else:
                        success_msg = message if message else "OTP sent successfully! Check your email."
                        return True, success_msg, result
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON success response")
                    return True, "OTP sent successfully! Check your email.", {}
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message") or error_data.get("error", f"Server error {response.status_code}")
                except json.JSONDecodeError:
                    error_msg = f"Server error {response.status_code}"
                return False, error_msg, {}
                
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Error sending OTP: {str(e)}", {}

    def verify_otp(self, email, otp, public_key, host_url="rfr1.resisti.net", vpn_name="testVPNapi"):
        """
        Verify the OTP and public key.
        Returns a tuple (success, message, data).

        TODO: Remove host_url and vpn_name parameters and get them from tha API instead!!!
        """
        try:
            api_url = f"{self.base_url}/verify-otp"
            payload = {
                "email": email,
                "otp": otp,
                "host_url": host_url,
                "vpn_name": vpn_name,
                "client_public_key": public_key
            }
            
            logger.debug("Sending verify-otp request...")
            response = requests.post(api_url, json=payload, timeout=90)
            
            if response.ok:
                try:
                    result = response.json()
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON success response")
                    result = {}
                
                status = result.get("status", "").lower()
                message = result.get("message", "")
                
                if status == "success" or status == "verified" or "success" in message.lower() or "verified" in message.lower():
                    return True, "OTP verified successfully!", result
                else:
                    return False, f"OTP verification failed: {message or 'Unknown error'}", result
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message") or error_data.get("error", f"Server error {response.status_code}")
                except json.JSONDecodeError:
                    error_msg = f"Server error {response.status_code}"
                return False, error_msg, {}
                
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Verification error: {str(e)}", {}
