"""Tests for plugins.dashboard.main — Dashboard Plugin logic.

Covers: initialization, _effective_appearance_mode, destroy cleanup,
and _rebuild_grid guard.
"""

from unittest.mock import MagicMock

import pytest

from plugins.dashboard.main import Plugin


@pytest.fixture()
def dashboard_plugin():
    app = MagicMock()
    app.plugin_list = []
    return Plugin(app)


@pytest.mark.unit
class TestDashboardInit:
    def test_attributes(self, dashboard_plugin):
        assert dashboard_plugin.get_name() == "Dashboard"
        assert dashboard_plugin.order == 1
        assert dashboard_plugin.uninstall_enabled is False

    def test_id(self, dashboard_plugin):
        assert dashboard_plugin.id == "001"


@pytest.mark.unit
class TestEffectiveAppearanceMode:
    def test_returns_current_mode(self, dashboard_plugin):
        import customtkinter
        customtkinter.get_appearance_mode.return_value = "Dark"
        assert dashboard_plugin._effective_appearance_mode() == "Dark"

    def test_returns_system(self, dashboard_plugin):
        import customtkinter
        customtkinter.get_appearance_mode.return_value = "System"
        assert dashboard_plugin._effective_appearance_mode() == "System"


@pytest.mark.unit
class TestDestroy:
    def test_cancels_resize_timer(self, dashboard_plugin):
        dashboard_plugin._resize_after_id = 42
        dashboard_plugin._resize_handler_id = None
        dashboard_plugin.destroy()
        dashboard_plugin.app.after_cancel.assert_called_with(42)

    def test_unbinds_resize_handler(self, dashboard_plugin):
        dashboard_plugin._resize_after_id = None
        dashboard_plugin._resize_handler_id = "handler_123"
        dashboard_plugin.destroy()
        dashboard_plugin.app.unbind.assert_called_with(
            "<Configure>", "handler_123",
        )

    def test_destroy_no_resize_state(self, dashboard_plugin):
        # No _resize_after_id or _resize_handler_id — should not raise
        dashboard_plugin.destroy()

    def test_destroy_handles_cancel_error(self, dashboard_plugin):
        dashboard_plugin._resize_after_id = 42
        dashboard_plugin._resize_handler_id = None
        dashboard_plugin.app.after_cancel.side_effect = RuntimeError("gone")
        dashboard_plugin.destroy()  # Should not raise


@pytest.mark.unit
class TestRebuildGrid:
    def test_guard_no_plugins(self, dashboard_plugin):
        # No _dashboard_plugins attribute
        dashboard_plugin._rebuild_grid(4)  # Should not raise

    def test_guard_no_content_frame(self, dashboard_plugin):
        dashboard_plugin._dashboard_plugins = [MagicMock()]
        # No _content_frame attribute
        dashboard_plugin._rebuild_grid(4)  # Should not raise

    def test_rebuilds_with_new_cols(self, dashboard_plugin):
        mock_plugin = MagicMock()
        dashboard_plugin._dashboard_plugins = [mock_plugin, mock_plugin]
        dashboard_plugin._content_frame = MagicMock()
        old_grid = MagicMock()
        dashboard_plugin.grid_frame = old_grid
        dashboard_plugin.app.calculate_rows_cols.return_value = ([0], [0, 1])
        new_grid = MagicMock()
        dashboard_plugin.app.create_grid.return_value = new_grid

        dashboard_plugin._rebuild_grid(2)

        old_grid.destroy.assert_called_once()
        dashboard_plugin.app.create_grid.assert_called_once()
        assert dashboard_plugin._current_cols == 2
        assert dashboard_plugin.grid_frame is new_grid
