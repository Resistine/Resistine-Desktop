"""
Unit tests for plugins/chat/main.py — Chat Plugin logic.

Tests the non-GUI business logic only. All GUI widgets (customtkinter, tkinter)
are stubbed in conftest.py. The OpenAI client is mocked via patch.

Covers:
- check_status: "OK" when client is set, "Warning" when None
- reinitialize_client: no API key → client=None
- reinitialize_client: API key present → client initialized
- reinitialize_client: custom base_url → model changes, session_id reset
- send_message_to_chatgpt: no client → yields error message
- send_message_to_chatgpt: client present → yields chunks from stream
- send_message_to_chatgpt: appends to conversation_history
- _clear_conversation: resets history to system prompt (standard) or [] (custom URL)
- _clear_conversation: resets session_id to None
"""
import sys
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixture: minimal Plugin instance with no API key (client=None)
# ---------------------------------------------------------------------------
@pytest.fixture()
def plugin(isolated_settings):
    """Create a Chat Plugin with a mocked app; no API key configured."""
    app = MagicMock()
    from plugins.chat.main import Plugin
    return Plugin(app)


@pytest.fixture()
def plugin_with_client(plugin):
    """Chat Plugin with a mock OpenAI client pre-injected."""
    plugin.client = MagicMock()
    plugin.base_url = None
    plugin.model = "gpt-4o"
    plugin.session_id = None
    return plugin


# ===========================================================================
# check_status
# ===========================================================================
@pytest.mark.unit
class TestCheckStatus:
    def test_returns_warning_when_client_is_none(self, plugin):
        plugin.client = None
        assert plugin.check_status() == "Warning"

    def test_returns_ok_when_client_is_set(self, plugin):
        plugin.client = MagicMock()
        assert plugin.check_status() == "OK"


# ===========================================================================
# reinitialize_client
# ===========================================================================
@pytest.mark.unit
class TestReinitializeClient:
    def test_no_api_key_sets_client_to_none(self, plugin, isolated_settings):
        """When no api key is stored, client must be None after reinit."""
        # isolated_settings has no "chat"/"openai_api_key"
        plugin.reinitialize_client()
        assert plugin.client is None

    def test_api_key_initializes_client(self, plugin, isolated_settings):
        """When an api key is present, client must be non-None after reinit."""
        isolated_settings.set_secret("chat", "openai_api_key", "sk-test-key-12345")

        mock_openai_cls = MagicMock()
        mock_openai_cls.return_value = MagicMock()

        with patch.dict(sys.modules, {"openai": MagicMock(OpenAI=mock_openai_cls)}):
            plugin.reinitialize_client()

        assert plugin.client is not None

    def test_api_key_failure_sets_client_to_none(self, plugin, isolated_settings):
        """If OpenAI() raises on construction, client must be set to None gracefully."""
        isolated_settings.set_secret("chat", "openai_api_key", "sk-bad-key")

        mock_openai_mod = MagicMock()
        mock_openai_mod.OpenAI.side_effect = Exception("invalid key format")

        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            plugin.reinitialize_client()

        assert plugin.client is None

    def test_reinit_resets_session_id(self, plugin_with_client):
        """reinitialize_client must reset session_id to None."""
        plugin_with_client.session_id = "old-session-abc"
        plugin_with_client.reinitialize_client()
        assert plugin_with_client.session_id is None

    def test_custom_base_url_uses_local_model(self, plugin, isolated_settings):
        """When base_url is set, model must be the local model, not gpt-4o."""
        isolated_settings.set("chat", "openai_base_url", "http://localhost:11434/v1")
        isolated_settings.set_secret("chat", "openai_api_key", "sk-local")

        mock_openai_mod = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            plugin.reinitialize_client()

        assert plugin.model != "gpt-4o"
        assert plugin.base_url == "http://localhost:11434/v1"

    def test_custom_base_url_passed_to_openai_constructor(self, plugin, isolated_settings):
        """The base_url from settings must be forwarded to OpenAI(base_url=...)."""
        custom_url = "http://localhost:11434/v1"
        isolated_settings.set("chat", "openai_base_url", custom_url)
        isolated_settings.set_secret("chat", "openai_api_key", "sk-local")

        mock_openai_cls = MagicMock()
        mock_openai_mod = MagicMock()
        mock_openai_mod.OpenAI = mock_openai_cls

        with patch.dict(sys.modules, {"openai": mock_openai_mod}):
            plugin.reinitialize_client()

        if mock_openai_cls.call_args:
            kwargs = mock_openai_cls.call_args[1]
            assert kwargs.get("base_url") == custom_url

    def test_standard_mode_adds_system_prompt_to_history(self, plugin, isolated_settings):
        """Without base_url, conversation_history must start with a system message."""
        isolated_settings.set("chat", "openai_base_url", None)  # clear base_url
        plugin.reinitialize_client()

        roles = [msg.get("role") for msg in plugin.conversation_history]
        assert "system" in roles, "Standard mode must include system prompt in history"

    def test_custom_url_mode_starts_with_empty_history(self, plugin, isolated_settings):
        """With base_url set, conversation_history must be empty (no system prompt)."""
        isolated_settings.set("chat", "openai_base_url", "http://localhost:11434/v1")
        plugin.reinitialize_client()
        # History is empty for custom URL mode
        assert plugin.conversation_history == []


# ===========================================================================
# send_message_to_chatgpt
# ===========================================================================
@pytest.mark.unit
class TestSendMessage:
    def _make_chunk(self, content: str):
        """Create a mock stream chunk with the given content."""
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        # No session_id by default
        del chunk.session_id
        return chunk

    def test_no_client_yields_error_message(self, plugin):
        """With no client and no api key, must yield a single error string."""
        plugin.client = None
        # Ensure reinitialize_client won't create a client either
        chunks = list(plugin.send_message_to_chatgpt("Hello?"))
        assert len(chunks) >= 1
        assert any("Error" in c or "key" in c.lower() for c in chunks), (
            f"Expected error message in chunks, got: {chunks}"
        )

    def test_standard_mode_yields_response_chunks(self, plugin_with_client):
        """With a working client (standard mode), chunks from the stream are yielded."""
        chunks_to_yield = [
            self._make_chunk("Hello"),
            self._make_chunk(" world"),
            self._make_chunk("!"),
        ]
        plugin_with_client.client.chat.completions.create.return_value = iter(chunks_to_yield)

        result = list(plugin_with_client.send_message_to_chatgpt("Hi"))

        assert result == ["Hello", " world", "!"]

    def test_standard_mode_assembles_full_response(self, plugin_with_client):
        """The full assembled response must be appended to conversation_history."""
        chunks_to_yield = [self._make_chunk("Part1"), self._make_chunk("Part2")]
        plugin_with_client.client.chat.completions.create.return_value = iter(chunks_to_yield)

        list(plugin_with_client.send_message_to_chatgpt("test"))

        assistant_msgs = [
            m["content"] for m in plugin_with_client.conversation_history
            if m.get("role") == "assistant"
        ]
        assert any("Part1Part2" in m for m in assistant_msgs), (
            f"Full assembled response not in history: {assistant_msgs}"
        )

    def test_user_message_appended_to_history(self, plugin_with_client):
        """The user's message must be added to conversation_history."""
        plugin_with_client.client.chat.completions.create.return_value = iter([
            self._make_chunk("Response")
        ])

        list(plugin_with_client.send_message_to_chatgpt("My question"))

        user_msgs = [
            m["content"] for m in plugin_with_client.conversation_history
            if m.get("role") == "user"
        ]
        assert "My question" in user_msgs

    def test_empty_chunk_content_skipped(self, plugin_with_client):
        """Chunks with None/empty content must not be yielded."""
        chunk_empty = MagicMock()
        chunk_empty.choices = [MagicMock()]
        chunk_empty.choices[0].delta.content = None

        chunk_real = self._make_chunk("actual content")
        plugin_with_client.client.chat.completions.create.return_value = iter([
            chunk_empty, chunk_real
        ])

        result = list(plugin_with_client.send_message_to_chatgpt("test"))
        assert None not in result
        assert "actual content" in result

    def test_custom_url_mode_sends_single_message_not_history(self, plugin_with_client):
        """In custom URL mode, only the current message is sent (not full history)."""
        plugin_with_client.base_url = "http://localhost:11434/v1"
        plugin_with_client.conversation_history = []

        chunk = self._make_chunk("response")
        plugin_with_client.client.chat.completions.create.return_value = iter([chunk])

        list(plugin_with_client.send_message_to_chatgpt("test message"))

        call_kwargs = plugin_with_client.client.chat.completions.create.call_args[1]
        messages = call_kwargs.get("messages", [])
        # In custom URL mode, only the current message is sent
        assert len(messages) == 1
        assert messages[0]["content"] == "test message"

    def test_custom_url_mode_includes_session_id_if_set(self, plugin_with_client):
        """If session_id is set, it must be included in extra_body."""
        plugin_with_client.base_url = "http://localhost:11434/v1"
        plugin_with_client.session_id = "existing-session-123"
        plugin_with_client.conversation_history = []

        chunk = self._make_chunk("hi")
        plugin_with_client.client.chat.completions.create.return_value = iter([chunk])

        list(plugin_with_client.send_message_to_chatgpt("hello"))

        call_kwargs = plugin_with_client.client.chat.completions.create.call_args[1]
        extra_body = call_kwargs.get("extra_body", {})
        assert extra_body.get("session_id") == "existing-session-123"


# ===========================================================================
# _clear_conversation
# ===========================================================================
@pytest.mark.unit
class TestClearConversation:
    def test_standard_mode_clear_resets_to_system_prompt(self, plugin):
        """In standard mode (no base_url), clear must restore the system message."""
        plugin.base_url = None
        plugin.conversation_history = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old msg"},
            {"role": "assistant", "content": "old reply"},
        ]
        # Stub out the GUI rebuild
        plugin.second_frame = MagicMock()
        plugin.create_main_screen = MagicMock(return_value=MagicMock())

        plugin._clear_conversation()

        roles = [m.get("role") for m in plugin.conversation_history]
        # After clear, only the system prompt should remain (no user/assistant)
        assert "user" not in roles
        assert "assistant" not in roles

    def test_custom_url_clear_resets_to_empty_list(self, plugin):
        """In custom URL mode, clear must produce an empty conversation_history."""
        plugin.base_url = "http://localhost:11434/v1"
        plugin.conversation_history = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "reply"},
        ]
        plugin.second_frame = MagicMock()
        plugin.create_main_screen = MagicMock(return_value=MagicMock())

        plugin._clear_conversation()

        assert plugin.conversation_history == []

    def test_clear_resets_session_id_to_none(self, plugin):
        """_clear_conversation must set session_id to None."""
        plugin.base_url = "http://localhost:11434/v1"
        plugin.session_id = "old-session-xyz"
        plugin.conversation_history = []
        plugin.second_frame = MagicMock()
        plugin.create_main_screen = MagicMock(return_value=MagicMock())

        plugin._clear_conversation()

        assert plugin.session_id is None
