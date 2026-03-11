# TODO: Remove host_url and vpn_name parameters and get them from tha API instead!!!
# TODO: Remove private_key and IP parameters and get it from the API instead!!!
# TODO: Create tests.
# TODO: Create documentation.

import json

import requests

from utils.logger import logger


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

            logger.info(f"[LOGIN] send_otp -> POST {api_url} | email={email}")
            response = requests.post(api_url, json=payload, timeout=90)
            logger.info(f"[LOGIN] send_otp <- HTTP {response.status_code} | body={response.text}")

            if response.ok:
                try:
                    result = response.json()
                    message = result.get("message", "")
                    status = result.get("status", "").lower()
                    logger.info(f"[LOGIN] send_otp parsed: status='{status}' message='{message}' keys={list(result.keys())}")

                    if status in ["error", "failed", "failure", "no_subscription"]:
                        error_msg = message or result.get("error", "Failed to send OTP")
                        return False, error_msg, result
                    else:
                        success_msg = (
                            message
                            if message
                            else "OTP sent successfully! Check your email."
                        )
                        return True, success_msg, result
                except json.JSONDecodeError:
                    logger.warning(f"[LOGIN] send_otp: non-JSON response body: {response.text}")
                    return True, "OTP sent successfully! Check your email.", {}
            else:
                try:
                    error_data = response.json()
                    logger.info(f"[LOGIN] send_otp error response: {error_data}")
                    error_msg = error_data.get("message") or error_data.get(
                        "error", f"Server error {response.status_code}"
                    )
                except json.JSONDecodeError:
                    error_msg = f"Server error {response.status_code}"
                return False, error_msg, {}

        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Error sending OTP: {str(e)}", {}

    def verify_otp(
        self,
        email: str,
        otp: str,
        public_key: str,
        hostname: str = None,
    ) -> tuple:
        """
        Verify the OTP and send the client public key to receive a WireGuard config.
        Returns a tuple (success, message, data).

        The server determines VPN assignment from the user's account subscription.
        """
        try:
            import socket

            api_url = f"{self.base_url}/verify-otp"
            payload = {
                "email": email,
                "otp": otp,
                "client_public_key": public_key,
                "hostname": hostname or socket.gethostname(),
            }

            logger.info(f"[LOGIN] verify_otp -> POST {api_url} | email={email} | hostname={payload['hostname']}")
            response = requests.post(api_url, json=payload, timeout=90)
            logger.info(f"[LOGIN] verify_otp <- HTTP {response.status_code} | body={response.text}")

            if response.ok:
                try:
                    result = response.json()
                except json.JSONDecodeError:
                    logger.warning(f"[LOGIN] verify_otp: non-JSON response body: {response.text}")
                    result = {}

                status = result.get("status", "").lower()
                message = result.get("message", "")
                logger.info(f"[LOGIN] verify_otp parsed: status='{status}' message='{message}' keys={list(result.keys())}")

                if (
                    status == "success"
                    or status == "verified"
                    or "success" in message.lower()
                    or "verified" in message.lower()
                ):
                    return True, "OTP verified successfully!", result
                else:
                    return (
                        False,
                        f"OTP verification failed: {message or 'Unknown error'}",
                        result,
                    )
            else:
                try:
                    error_data = response.json()
                    logger.info(f"[LOGIN] verify_otp error response: {error_data}")
                    error_msg = error_data.get("message") or error_data.get(
                        "error", f"Server error {response.status_code}"
                    )
                except json.JSONDecodeError:
                    error_msg = f"Server error {response.status_code}"
                return False, error_msg, {}

        except requests.exceptions.RequestException as e:
            return False, f"Network error: {str(e)}", {}
        except Exception as e:
            return False, f"Verification error: {str(e)}", {}
