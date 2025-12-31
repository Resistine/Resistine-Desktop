import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.getcwd())

# Mock customtkinter before importing user_interface
sys.modules["customtkinter"] = MagicMock()
sys.modules["customtkinter.theme_manager"] = MagicMock()
sys.modules["customtkinter.theme_manager"].ThemeManager = MagicMock()

# Now import user_interface
from utils import user_interface


class TestAppUI(unittest.TestCase):
    def test_app_ui_mixin(self):
        # Create a mock App class that inherits from AppUI
        class MockApp(user_interface.AppUI):
            def __init__(self):
                self.winfo_children = MagicMock(return_value=[])
                self.grid_rowconfigure = MagicMock()
                self.grid_columnconfigure = MagicMock()
                self.title = MagicMock()
                self.geometry = MagicMock()
                self.update = MagicMock()

        app = MockApp()

        # Verify methods exist
        self.assertTrue(hasattr(app, "create_dashboard"))
        self.assertTrue(hasattr(app, "select_frame_by_name"))
        self.assertTrue(hasattr(app, "refresh_ui_theme"))

        # Mocking for execution
        with patch("utils.user_interface.PluginManager") as MockPluginManager:
            mock_plugin = MagicMock()
            mock_plugin.get_name.return_value = "Dashboard"
            MockPluginManager.return_value.plugins = [mock_plugin]

            # We don't need to patch customtkinter here if we mocked the module,
            # BUT user_interface might have already imported it.
            # However, since we mock sys.modules BEFORE import, user_interface.customtkinter
            # will be the mock.

            try:
                app.create_dashboard()
                print("create_dashboard (mixin) executed successfully")

                app.select_frame_by_name("frame_Dashboard")
                print("select_frame_by_name (mixin) executed successfully")

                app.refresh_ui_theme()
                print("refresh_ui_theme (mixin) executed successfully")

            except Exception as e:
                self.fail(f"Mixin execution failed: {e}")


if __name__ == "__main__":
    unittest.main()
