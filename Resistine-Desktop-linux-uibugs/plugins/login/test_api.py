import unittest
from unittest.mock import MagicMock, patch
import requests
from plugins.login.api import LoginAPI

class TestLoginAPI(unittest.TestCase):
    def setUp(self):
        self.base_url = "https://test.resistine.work"
        self.api = LoginAPI(self.base_url)

    @patch('plugins.login.api.requests.post')
    def test_send_otp_success(self, mock_post):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"status": "success", "message": "OTP sent"}
        mock_post.return_value = mock_response

        success, message, result = self.api.send_otp("test@example.com")

        self.assertTrue(success)
        self.assertEqual(message, "OTP sent")
        self.assertEqual(result, {"status": "success", "message": "OTP sent"})
        mock_post.assert_called_once()

    @patch('plugins.login.api.requests.post')
    def test_send_otp_failure_response(self, mock_post):
        # Mock failure response from server
        mock_response = MagicMock()
        mock_response.ok = True # HTTP 200 but status error
        mock_response.json.return_value = {"status": "error", "message": "Invalid email"}
        mock_post.return_value = mock_response

        success, message, result = self.api.send_otp("invalid@example.com")

        self.assertFalse(success)
        self.assertEqual(message, "Invalid email")

    @patch('plugins.login.api.requests.post')
    def test_send_otp_network_error(self, mock_post):
        # Mock network exception
        mock_post.side_effect = requests.exceptions.RequestException("Connection refused")

        success, message, result = self.api.send_otp("test@example.com")

        self.assertFalse(success)
        self.assertIn("Network error", message)

    @patch('plugins.login.api.requests.post')
    def test_verify_otp_success(self, mock_post):
        # Mock successful verification
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "status": "success", 
            "message": "Verified",
            "vpn_config": "{}"
        }
        mock_post.return_value = mock_response

        success, message, result = self.api.verify_otp("test@example.com", "123456", "pubkey")

        self.assertTrue(success)
        self.assertIn("verified successfully", message)
        self.assertIn("vpn_config", result)

    @patch('plugins.login.api.requests.post')
    def test_verify_otp_failure(self, mock_post):
        # Mock failed verification
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"status": "failed", "message": "Wrong OTP"}
        mock_post.return_value = mock_response

        success, message, result = self.api.verify_otp("test@example.com", "000000", "pubkey")

        self.assertFalse(success)
        self.assertIn("OTP verification failed", message)

    @patch('plugins.login.api.requests.post')
    def test_verify_otp_sends_hostname(self, mock_post):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"status": "success", "message": "Verified"}
        mock_post.return_value = mock_response

        self.api.verify_otp("test@example.com", "123456", "pubkey")

        # Verify hostname is included in the payload
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        self.assertIn("hostname", payload)
        self.assertIsInstance(payload["hostname"], str)
        self.assertNotEqual(payload["hostname"], "")

    @patch('plugins.login.api.requests.post')
    def test_verify_otp_custom_hostname(self, mock_post):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"status": "success", "message": "Verified"}
        mock_post.return_value = mock_response

        self.api.verify_otp("test@example.com", "123456", "pubkey", hostname="my-laptop")

        # Verify the custom hostname is sent
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        self.assertEqual(payload["hostname"], "my-laptop")

if __name__ == '__main__':
    unittest.main()
