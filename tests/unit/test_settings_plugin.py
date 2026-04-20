"""Tests for plugins.settings.main — Settings Plugin logic.

Covers: save_api_key, save_animation_setting, change_appearance_mode,
_effective_appearance_mode, _apply_theme_refresh, _get_app_version,
_handle_logout guard, _handle_uninstall guard, _check_for_updates.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure tkinter.messagebox is stubbed (conftest stubs tkinter as MagicMock,
# but "import tkinter.messagebox" inside methods fails because it tries to
# load a submodule of a MagicMock).
if "tkinter.messagebox" not in sys.modules:
    sys.modules["tkinter.messagebox"] = MagicMock()


@pytest.fixture()
def settings_plugin(isolated_settings):
    """Create a Settings Plugin with mocked app."""
    app = MagicMock()
    from plugins.settings.main import Plugin
    return Plugin(app)


# ---------------------------------------------------------------------------
# save_api_key
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSaveApiKey:
    def test_saves_key_and_base_url(self, settings_plugin, isolated_settings):
        settings_plugin.api_key_entry = MagicMock()
        settings_plugin.api_key_entry.get.return_value = "sk-test-key"
        settings_plugin.api_base_entry = MagicMock()
        settings_plugin.api_base_entry.get.return_value = "http://localhost:11434/v1"
        settings_plugin.status_label = MagicMock()
        settings_plugin.app.plugin_list = []

        settings_plugin.save_api_key()

        assert isolated_settings.get_secret("chat", "openai_api_key") == "sk-test-key"
        assert isolated_settings.get("chat", "openai_base_url") == "http://localhost:11434/v1"

    def test_empty_key_does_nothing(self, settings_plugin, isolated_settings):
        settings_plugin.api_key_entry = MagicMock()
        settings_plugin.api_key_entry.get.return_value = "   "
        settings_plugin.api_base_entry = MagicMock()
        settings_plugin.api_base_entry.get.return_value = ""
        settings_plugin.status_label = MagicMock()

        settings_plugin.save_api_key()

        assert isolated_settings.get_secret("chat", "openai_api_key") is None

    def test_clears_base_url_when_empty(self, settings_plugin, isolated_settings):
        isolated_settings.set("chat", "openai_base_url", "http://old.url")

        settings_plugin.api_key_entry = MagicMock()
        settings_plugin.api_key_entry.get.return_value = "sk-key"
        settings_plugin.api_base_entry = MagicMock()
        settings_plugin.api_base_entry.get.return_value = ""
        settings_plugin.status_label = MagicMock()
        settings_plugin.app.plugin_list = []

        settings_plugin.save_api_key()

        assert isolated_settings.get("chat", "openai_base_url") is None

    def test_reinitializes_chat_plugin(self, settings_plugin, isolated_settings):
        mock_chat = MagicMock()
        mock_chat.get_name.return_value = "Chat"
        settings_plugin.app.plugin_list = [mock_chat]

        settings_plugin.api_key_entry = MagicMock()
        settings_plugin.api_key_entry.get.return_value = "sk-key"
        settings_plugin.api_base_entry = MagicMock()
        settings_plugin.api_base_entry.get.return_value = ""
        settings_plugin.status_label = MagicMock()

        settings_plugin.save_api_key()

        mock_chat.reinitialize_client.assert_called_once()


# ---------------------------------------------------------------------------
# save_animation_setting
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSaveAnimationSetting:
    def test_saves_true(self, settings_plugin, isolated_settings):
        settings_plugin.disable_animation_var = MagicMock()
        settings_plugin.disable_animation_var.get.return_value = True
        settings_plugin.save_animation_setting()
        assert isolated_settings.get("chat", "disable_animation") is True

    def test_saves_false(self, settings_plugin, isolated_settings):
        settings_plugin.disable_animation_var = MagicMock()
        settings_plugin.disable_animation_var.get.return_value = False
        settings_plugin.save_animation_setting()
        assert isolated_settings.get("chat", "disable_animation") is False


# ---------------------------------------------------------------------------
# change_appearance_mode
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestChangeAppearanceMode:
    def test_calls_set_appearance_mode(self, settings_plugin):
        import customtkinter
        settings_plugin.change_appearance_mode("Dark")
        customtkinter.set_appearance_mode.assert_called_with("Dark")

    def test_applies_theme_refresh(self, settings_plugin):
        with patch.object(settings_plugin, "_apply_theme_refresh") as mock_refresh:
            settings_plugin.change_appearance_mode("Light")
            mock_refresh.assert_called_once()


# ---------------------------------------------------------------------------
# _effective_appearance_mode
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEffectiveAppearanceMode:
    def test_returns_mode_when_not_system(self, settings_plugin):
        import customtkinter
        customtkinter.get_appearance_mode.return_value = "Dark"
        assert settings_plugin._effective_appearance_mode() == "Dark"

    def test_system_mode_darwin_dark(self, settings_plugin, monkeypatch):
        import customtkinter
        customtkinter.get_appearance_mode.return_value = "System"
        monkeypatch.setattr("sys.platform", "darwin")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Dark")
            result = settings_plugin._effective_appearance_mode()
            assert result == "Dark"

    def test_system_mode_darwin_light(self, settings_plugin, monkeypatch):
        import customtkinter
        customtkinter.get_appearance_mode.return_value = "System"
        monkeypatch.setattr("sys.platform", "darwin")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = settings_plugin._effective_appearance_mode()
            assert result == "Light"

    def test_system_mode_non_darwin(self, settings_plugin, monkeypatch):
        import customtkinter
        customtkinter.get_appearance_mode.return_value = "System"
        monkeypatch.setattr("sys.platform", "linux")
        result = settings_plugin._effective_appearance_mode()
        assert result == "Light"


# ---------------------------------------------------------------------------
# _apply_theme_refresh
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestApplyThemeRefresh:
    def test_calls_refresh_ui_theme(self, settings_plugin):
        settings_plugin.app.refresh_ui_theme = MagicMock()
        settings_plugin._apply_theme_refresh()
        settings_plugin.app.refresh_ui_theme.assert_called_once()

    def test_falls_back_to_update_idletasks(self, settings_plugin):
        settings_plugin.app.refresh_ui_theme = MagicMock(side_effect=RuntimeError("fail"))
        settings_plugin._apply_theme_refresh()
        settings_plugin.app.update_idletasks.assert_called()

    def test_no_refresh_method(self, settings_plugin):
        del settings_plugin.app.refresh_ui_theme
        settings_plugin._apply_theme_refresh()
        settings_plugin.app.update_idletasks.assert_called()


# ---------------------------------------------------------------------------
# _get_app_version
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetAppVersion:
    def test_frozen_reads_plist(self, settings_plugin, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        macos_dir = tmp_path / "Contents" / "MacOS"
        macos_dir.mkdir(parents=True)
        monkeypatch.setattr("sys.executable", str(macos_dir / "Resistine"))

        import plistlib
        plist_path = tmp_path / "Contents" / "Info.plist"
        with open(plist_path, "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "2.5.1"}, f)

        assert settings_plugin._get_app_version() == "2.5.1"

    def test_source_mode_fallback(self, settings_plugin, monkeypatch):
        monkeypatch.setattr("sys.frozen", False, raising=False)
        with patch("utils.updates.version.get_current_version", return_value="3.0.0"):
            assert settings_plugin._get_app_version() == "3.0.0"

    def test_ultimate_fallback(self, settings_plugin, monkeypatch):
        monkeypatch.setattr("sys.frozen", False, raising=False)
        with patch("utils.updates.version.get_current_version", side_effect=ImportError):
            assert settings_plugin._get_app_version() == "1.0.0"


# ---------------------------------------------------------------------------
# _handle_logout
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHandleLogout:
    def _set_messagebox(self, return_value):
        """Set tkinter.messagebox.askyesno on the mock tkinter parent."""
        tk = sys.modules["tkinter"]
        tk.messagebox.askyesno = MagicMock(return_value=return_value)

    def test_user_cancels(self, settings_plugin):
        self._set_messagebox(False)
        settings_plugin._handle_logout()

    def test_clears_auth_on_confirm(self, settings_plugin, isolated_settings):
        isolated_settings.set("auth", "logged_in", True)
        self._set_messagebox(True)
        with patch("plugins.vpn.wireguard.vpn_functions_darwin.stop_vpn"), \
             patch("plugins.login.main.Plugin"):
            settings_plugin._handle_logout()
        assert isolated_settings.get("auth", "logged_in") is False


# ---------------------------------------------------------------------------
# _handle_uninstall
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHandleUninstall:
    def _set_messagebox(self, return_value):
        tk = sys.modules["tkinter"]
        tk.messagebox.askyesno = MagicMock(return_value=return_value)

    def test_user_cancels(self, settings_plugin):
        self._set_messagebox(False)
        settings_plugin._handle_uninstall()

    def test_uninstall_success_destroys_app(self, settings_plugin):
        settings_plugin.uninstall_button = MagicMock()
        settings_plugin.uninstall_status_label = MagicMock()
        self._set_messagebox(True)

        with patch("utils.uninstall.run_uninstall", return_value=(True, "ok")):
            settings_plugin._handle_uninstall()
            settings_plugin.app.destroy.assert_called_once()

    def test_uninstall_failure_shows_error(self, settings_plugin):
        settings_plugin.uninstall_button = MagicMock()
        settings_plugin.uninstall_status_label = MagicMock()
        self._set_messagebox(True)

        with patch("utils.uninstall.run_uninstall", return_value=(False, "denied")):
            settings_plugin._handle_uninstall()
            settings_plugin.app.destroy.assert_not_called()
            settings_plugin.uninstall_button.configure.assert_called()


# ---------------------------------------------------------------------------
# _check_for_updates
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCheckForUpdates:
    def test_updates_not_available(self, settings_plugin):
        settings_plugin.update_status_label = MagicMock()
        with patch("utils.updates.is_available", return_value=False):
            settings_plugin._check_for_updates()
        last_call = settings_plugin.update_status_label.configure.call_args
        assert "not available" in last_call.kwargs["text"].lower()

    def test_check_success(self, settings_plugin):
        settings_plugin.update_status_label = MagicMock()
        with patch("utils.updates.is_available", return_value=True), \
             patch("utils.updates.check_for_updates", return_value=True):
            settings_plugin._check_for_updates()
        last_call = settings_plugin.update_status_label.configure.call_args
        assert "checking" in last_call.kwargs["text"].lower()

    def test_check_exception(self, settings_plugin):
        settings_plugin.update_status_label = MagicMock()
        with patch("utils.updates.is_available", side_effect=RuntimeError("boom")):
            settings_plugin._check_for_updates()
        last_call = settings_plugin.update_status_label.configure.call_args
        assert "error" in last_call.kwargs["text"].lower()
