import os
import sys
import traceback
from unittest.mock import MagicMock, patch

# Add the project root to sys.path
sys.path.append(os.getcwd())

from plugins.chat.main import Plugin as ChatPlugin
from utils import settings


def test_settings_storage():
    print("Testing settings storage...")
    namespace = "chat"
    key = "openai_base_url"
    test_url = "http://localhost:11434/v1"

    # Save test URL
    settings.set(namespace, key, test_url)
    retrieved_url = settings.get(namespace, key)
    assert retrieved_url == test_url, f"Expected {test_url}, got {retrieved_url}"
    print("✅ Settings storage verified.")


def test_chat_plugin_initialization():
    print("Testing Chat plugin initialization with base_url...")

    # Mock settings
    with patch("utils.settings.get_secret") as mock_get_secret, patch(
        "utils.settings.get"
    ) as mock_get, patch("plugins.chat.main.OpenAI") as mock_openai:

        mock_get_secret.return_value = "fake-api-key"
        mock_get.return_value = "http://custom-server.com/v1"

        # Create a mock app
        mock_app = MagicMock()

        # Initialize plugin
        plugin = ChatPlugin(mock_app)

        # Verify OpenAI was called with base_url
        mock_openai.assert_called_once_with(
            api_key="fake-api-key", base_url="http://custom-server.com/v1"
        )
        print("✅ Chat plugin initialized with custom base_url.")


def test_chat_plugin_initialization_no_base_url():
    print("Testing Chat plugin initialization without base_url...")

    # Mock settings
    with patch("utils.settings.get_secret") as mock_get_secret, patch(
        "utils.settings.get"
    ) as mock_get, patch("plugins.chat.main.OpenAI") as mock_openai:

        mock_get_secret.return_value = "fake-api-key"
        mock_get.return_value = None

        # Create a mock app
        mock_app = MagicMock()

        # Initialize plugin
        plugin = ChatPlugin(mock_app)

        # Verify OpenAI was called without base_url
        mock_openai.assert_called_once_with(api_key="fake-api-key")
        print("✅ Chat plugin initialized without custom base_url.")


if __name__ == "__main__":
    try:
        test_settings_storage()
        test_chat_plugin_initialization()
        test_chat_plugin_initialization_no_base_url()
        print("\nALL TESTS PASSED! 🎉")
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
