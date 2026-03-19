"""
Unit tests for plugins/base_plugin.py — BasePlugin.

GUI-heavy dependencies (customtkinter, PIL) are stubbed in conftest.py.

Covers:
- Initialization and attribute storage
- get_status / check_status normalization
- Exception in check_status returns "Warning"
- Status map coverage (ok, info, warning, error, critical)
- create_main_screen raises NotImplementedError
- destroy is a no-op
- uninstall — enabled / disabled / no app reference
- Getters/setters
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------
class ConcretePlugin:
    """Lazy import wrapper — avoids importing BasePlugin at collection time."""

    _instance = None

    @classmethod
    def make(cls, **kwargs):
        from plugins.base_plugin import BasePlugin

        class _Concrete(BasePlugin):
            def create_main_screen(self):
                return MagicMock()

        defaults = dict(
            id="test_001",
            version="2025.01.01",
            order=1,
            name="Test Plugin",
            status="OK",
            description="A test plugin",
            supported_systems=["Darwin", "Windows", "Linux"],
            translations={"US": "Test Plugin"},
            icon_light_path="/fake/light.png",
            icon_dark_path="/fake/dark.png",
            uninstall_enabled=True,
        )
        defaults.update(kwargs)
        with patch("plugins.base_plugin.Image.open", return_value=MagicMock()):
            return _Concrete(**defaults)


@pytest.fixture()
def plugin():
    return ConcretePlugin.make()


# ===========================================================================
# Initialization
# ===========================================================================
@pytest.mark.unit
class TestInit:
    def test_id_stored(self, plugin):
        assert plugin.id == "test_001"

    def test_version_stored(self, plugin):
        assert plugin.version == "2025.01.01"

    def test_name_stored(self, plugin):
        assert plugin.name == "Test Plugin"

    def test_status_stored(self, plugin):
        assert plugin.status == "OK"

    def test_description_stored(self, plugin):
        assert plugin.description == "A test plugin"

    def test_supported_systems_stored(self, plugin):
        assert "Darwin" in plugin.supported_systems

    def test_translations_stored(self, plugin):
        assert plugin.translations["US"] == "Test Plugin"

    def test_uninstall_enabled_defaults_true(self, plugin):
        assert plugin.uninstall_enabled is True

    def test_button_initially_none(self, plugin):
        assert plugin.button is None

    def test_app_initially_none(self, plugin):
        assert plugin.app is None


# ===========================================================================
# get_status / check_status
# ===========================================================================
@pytest.mark.unit
class TestGetStatus:
    @pytest.mark.parametrize("raw,expected", [
        ("ok", "OK"),
        ("OK", "OK"),
        ("info", "Info"),
        ("Info", "Info"),
        ("warning", "Warning"),
        ("Warning", "Warning"),
        ("error", "Error"),
        ("Error", "Error"),
        ("critical", "Critical"),
        ("Critical", "Critical"),
    ])
    def test_status_normalization(self, raw, expected):
        p = ConcretePlugin.make(status=raw)
        assert p.get_status() == expected

    def test_unknown_status_returned_as_is(self):
        p = ConcretePlugin.make(status="CustomStatus")
        assert p.get_status() == "CustomStatus"

    def test_none_status_returns_none(self):
        p = ConcretePlugin.make(status=None)
        assert p.get_status() is None

    def test_exception_in_check_status_returns_warning(self, plugin):
        def _crash():
            raise RuntimeError("status check failed")
        plugin.check_status = _crash
        assert plugin.get_status() == "Warning"


# ===========================================================================
# create_main_screen
# ===========================================================================
@pytest.mark.unit
def test_create_main_screen_raises_not_implemented():
    from plugins.base_plugin import BasePlugin
    with patch("plugins.base_plugin.Image.open", return_value=MagicMock()):
        p = BasePlugin.__new__(BasePlugin)
        # Call the abstract method directly
        with pytest.raises(NotImplementedError):
            BasePlugin.create_main_screen(p)


# ===========================================================================
# destroy
# ===========================================================================
@pytest.mark.unit
def test_destroy_is_noop(plugin):
    plugin.destroy()  # Should not raise


# ===========================================================================
# uninstall
# ===========================================================================
@pytest.mark.unit
class TestUninstall:
    def test_uninstall_disabled_returns_message(self):
        p = ConcretePlugin.make(uninstall_enabled=False)
        result = p.uninstall()
        assert "not enabled" in result

    def test_uninstall_without_app_returns_message(self, plugin):
        plugin.app = None
        result = plugin.uninstall()
        assert "Application instance" in result or "not found" in result

    def test_uninstall_with_app_delegates_to_manager(self, plugin):
        mock_mgr = MagicMock()
        mock_mgr.uninstall_plugin.return_value = "uninstalled"
        mock_app = MagicMock()
        mock_app.get_plugin_manager.return_value = mock_mgr
        plugin.app = mock_app
        result = plugin.uninstall()
        mock_mgr.uninstall_plugin.assert_called_once_with(plugin)


# ===========================================================================
# Getters / setters
# ===========================================================================
@pytest.mark.unit
class TestGettersSetters:
    def test_set_get_id(self, plugin):
        plugin.set_id("new_id")
        assert plugin.get_id() == "new_id"

    def test_set_get_name(self, plugin):
        plugin.set_name("New Name")
        assert plugin.get_name() == "New Name"

    def test_set_get_status(self, plugin):
        plugin.set_status("Error")
        assert plugin.status == "Error"

    def test_set_get_description(self, plugin):
        plugin.set_description("New desc")
        assert plugin.get_description() == "New desc"

    def test_set_get_translations(self, plugin):
        plugin.set_translations({"US": "Updated"})
        assert plugin.get_translations()["US"] == "Updated"

    def test_set_get_button(self, plugin):
        btn = MagicMock()
        plugin.set_button(btn)
        assert plugin.get_button() is btn

    def test_set_get_supported_systems(self, plugin):
        plugin.set_supported_systems(["Windows"])
        assert plugin.get_supported_systems() == ["Windows"]


# ===========================================================================
# is_resistine_config (VPN specific static check via config_manager)
# ===========================================================================
@pytest.mark.unit
def test_status_map_completeness():
    from plugins.base_plugin import BasePlugin
    expected_keys = {"ok", "info", "warning", "error", "critical"}
    assert expected_keys == set(BasePlugin.status_map.keys())
