"""Tests for plugins.antivirus.main — Plugin class logic methods.

Covers: check_status, _on_action routing, _handle_scan_complete,
_offer_quarantine_batch, destroy, and status state mapping.
"""

from unittest.mock import MagicMock, patch

import pytest

from plugins.antivirus.main import Plugin
from plugins.antivirus.scanner import ScanResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def plugin():
    """Create a Plugin instance with a mocked app."""
    with patch("plugins.antivirus.main.clamav") as mock_clamav, \
         patch("plugins.antivirus.main.threading"), \
         patch("platform.system", return_value="Darwin"):
        mock_clamav.get_realtime_status.return_value = {
            "state": "protected", "installed": True, "db_present": True,
            "approved": True, "fda_granted": True,
            "clamd_running": True, "clamonacc_running": True,
        }
        mock_clamav.is_clamav_installed.return_value = True

        app = MagicMock()
        p = Plugin(app)

        # Wire up mock UI components for scan-related tests
        p._scan_log = MagicMock()
        p._scan_progress = MagicMock()
        p._scan_status_label = MagicMock()
        p._action_buttons = {
            "scan_file": MagicMock(),
            "scan_directory": MagicMock(),
            "analysis": MagicMock(),
            "cancel_scan": MagicMock(),
            "update_sigs": MagicMock(),
        }
        return p


# ---------------------------------------------------------------------------
# check_status
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCheckStatus:
    def test_protected_returns_ok(self, plugin):
        plugin._last_state = "protected"
        assert plugin.check_status() == "OK"

    def test_error_returns_error(self, plugin):
        plugin._last_state = "error"
        assert plugin.check_status() == "Error"

    @pytest.mark.parametrize("state", [
        "not_installed", "no_database", "approval_required",
        "fda_required", None,
    ])
    def test_other_states_return_warning(self, plugin, state):
        plugin._last_state = state
        assert plugin.check_status() == "Warning"


# ---------------------------------------------------------------------------
# _on_action routing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOnAction:
    def test_routes_known_actions(self, plugin):
        for action_key in ("scan_file", "scan_directory", "analysis",
                           "update_sigs", "whitelist_add"):
            with patch.object(plugin, "_start_file_scan" if action_key == "scan_file"
                              else "_start_directory_scan" if action_key == "scan_directory"
                              else "_start_analysis" if action_key == "analysis"
                              else "_start_sig_update" if action_key == "update_sigs"
                              else "_add_whitelist_entry") as mock_handler:
                plugin._on_action(action_key)
                mock_handler.assert_called_once()

    def test_unknown_action_no_crash(self, plugin):
        # Should silently ignore unknown actions
        plugin._on_action("nonexistent_action")


# ---------------------------------------------------------------------------
# _handle_scan_complete
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHandleScanComplete:
    def test_clean_scan(self, plugin):
        plugin._last_state = "protected"
        result = ScanResult(
            target="/tmp/test", scanned=10, infected=0,
            duration="2.5 sec",
        )
        plugin._handle_scan_complete(result)

        assert plugin._scanning is False
        assert plugin._scan_handle is None
        plugin._scan_progress.stop.assert_called_once()
        plugin._scan_status_label.configure.assert_called()
        # Check final status says "No threats found"
        last_call = plugin._scan_status_label.configure.call_args
        assert "No threats" in last_call.kwargs.get("text", "")

    def test_infected_scan_offers_quarantine(self, plugin):
        plugin._last_state = "protected"
        result = ScanResult(
            target="/tmp/test", scanned=5, infected=2,
            infections=[
                "/tmp/test/virus1.exe: Win.Trojan FOUND",
                "/tmp/test/virus2.dll: Backdoor.Agent FOUND",
            ],
        )
        with patch.object(plugin, "_offer_quarantine_batch") as mock_offer:
            plugin._handle_scan_complete(result)
            mock_offer.assert_called_once()
            paths = mock_offer.call_args[0][0]
            assert "/tmp/test/virus1.exe" in paths
            assert "/tmp/test/virus2.dll" in paths

    def test_scan_error(self, plugin):
        plugin._last_state = "protected"
        result = ScanResult(target="/tmp/test", error="ClamAV crashed")
        plugin._handle_scan_complete(result)
        # Should show "Scan failed"
        calls = plugin._scan_status_label.configure.call_args_list
        texts = [c.kwargs.get("text", "") for c in calls]
        assert any("failed" in t.lower() for t in texts)

    def test_scan_cancelled(self, plugin):
        plugin._last_state = "protected"
        result = ScanResult(target="/tmp/test", error="Scan cancelled.")
        plugin._handle_scan_complete(result)
        calls = plugin._scan_status_label.configure.call_args_list
        texts = [c.kwargs.get("text", "") for c in calls]
        assert any("cancelled" in t.lower() for t in texts)

    def test_buttons_reenabled_after_scan(self, plugin):
        plugin._last_state = "protected"
        result = ScanResult(target="/tmp/test", scanned=1)
        plugin._handle_scan_complete(result)
        # Scan buttons should be re-enabled when state is "protected"
        for key in ("scan_file", "scan_directory", "analysis"):
            plugin._action_buttons[key].configure.assert_called()

    def test_buttons_disabled_when_no_database(self, plugin):
        plugin._last_state = "no_database"
        result = ScanResult(target="/tmp/test", scanned=0)
        plugin._handle_scan_complete(result)
        for key in ("scan_file", "scan_directory", "analysis"):
            btn = plugin._action_buttons[key]
            last_call = btn.configure.call_args
            assert last_call.kwargs.get("state") == "disabled"

    def test_cancel_button_hidden_after_scan(self, plugin):
        plugin._last_state = "protected"
        result = ScanResult(target="/tmp/test", scanned=1)
        plugin._handle_scan_complete(result)
        plugin._action_buttons["cancel_scan"].grid_remove.assert_called()


# ---------------------------------------------------------------------------
# _cancel_scan
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCancelScan:
    def test_cancel_active_scan(self, plugin):
        handle = MagicMock()
        handle.cancelled = False
        plugin._scan_handle = handle
        plugin._cancel_scan()
        handle.cancel.assert_called_once()

    def test_cancel_no_active_scan(self, plugin):
        plugin._scan_handle = None
        # Should not raise
        plugin._cancel_scan()

    def test_cancel_already_cancelled(self, plugin):
        handle = MagicMock()
        handle.cancelled = True
        plugin._scan_handle = handle
        plugin._cancel_scan()
        handle.cancel.assert_not_called()


# ---------------------------------------------------------------------------
# _offer_quarantine_batch
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOfferQuarantineBatch:
    def test_user_accepts(self, plugin):
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = True
            mock_clamav.quarantine_file.return_value = (True, "/quarantine/virus.exe.quarantined")

            plugin._offer_quarantine_batch(["/tmp/virus.exe"])

            mock_clamav.quarantine_file.assert_called_once_with("/tmp/virus.exe")

    def test_user_declines(self, plugin):
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = False

            plugin._offer_quarantine_batch(["/tmp/virus.exe"])

            mock_clamav.quarantine_file.assert_not_called()

    def test_quarantine_failure_logged(self, plugin):
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = True
            mock_clamav.quarantine_file.return_value = (False, "Permission denied")
            mock_clamav.list_quarantined.return_value = []

            plugin._offer_quarantine_batch(["/tmp/virus.exe"])

            # Should still complete without raising
            mock_clamav.quarantine_file.assert_called_once()

    def test_truncates_long_listing(self, plugin):
        """Message shows first 20 files and '... and N more'."""
        files = [f"/tmp/virus{i}.exe" for i in range(25)]
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = False
            plugin._offer_quarantine_batch(files)
            msg = mock_mb.askyesno.call_args[0][1]
            assert "25 infected" in msg
            assert "5 more" in msg


# ---------------------------------------------------------------------------
# _start_file_scan / _start_directory_scan guards
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScanGuards:
    def test_file_scan_blocked_while_scanning(self, plugin):
        plugin._scanning = True
        with patch("plugins.antivirus.main.filedialog") as mock_fd:
            plugin._start_file_scan()
            mock_fd.askopenfilename.assert_not_called()

    def test_directory_scan_blocked_while_scanning(self, plugin):
        plugin._scanning = True
        with patch("plugins.antivirus.main.filedialog") as mock_fd:
            plugin._start_directory_scan()
            mock_fd.askdirectory.assert_not_called()

    def test_analysis_blocked_while_scanning(self, plugin):
        plugin._scanning = True
        # Should not call _run_scan
        with patch.object(plugin, "_run_scan") as mock_run:
            plugin._start_analysis()
            mock_run.assert_not_called()

    def test_file_scan_cancelled_dialog(self, plugin):
        plugin._scanning = False
        with patch("plugins.antivirus.main.filedialog") as mock_fd, \
             patch.object(plugin, "_run_scan") as mock_run:
            mock_fd.askopenfilename.return_value = ""
            plugin._start_file_scan()
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDestroy:
    def test_destroy_clears_banner_refs(self, plugin):
        plugin._banner_frame = MagicMock()
        plugin._banner_label = MagicMock()
        plugin._banner_subtitle = MagicMock()
        plugin._banner_action_btn = MagicMock()
        plugin.main_frame = MagicMock()

        plugin.destroy()

        assert plugin._banner_frame is None
        assert plugin._banner_label is None
        assert plugin._banner_subtitle is None
        assert plugin._banner_action_btn is None
        assert plugin.main_frame is None

    def test_destroy_no_main_frame(self, plugin):
        plugin.main_frame = None
        # Should not raise
        plugin.destroy()


# ---------------------------------------------------------------------------
# _toggle_auto_update
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestToggleAutoUpdate:
    def test_toggle_on(self, plugin):
        plugin._auto_update_switch = MagicMock()
        plugin._auto_update_switch.get.return_value = True
        plugin._toggle_auto_update()
        assert plugin._auto_update_on is True

    def test_toggle_off(self, plugin):
        plugin._auto_update_switch = MagicMock()
        plugin._auto_update_switch.get.return_value = False
        plugin._toggle_auto_update()
        assert plugin._auto_update_on is False


# ---------------------------------------------------------------------------
# _set_scan_buttons_state
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSetScanButtonsState:
    def test_enables_all(self, plugin):
        plugin._set_scan_buttons_state("normal")
        for key in ("scan_file", "scan_directory", "analysis"):
            plugin._action_buttons[key].configure.assert_called_with(state="normal")

    def test_disables_all(self, plugin):
        plugin._set_scan_buttons_state("disabled")
        for key in ("scan_file", "scan_directory", "analysis"):
            plugin._action_buttons[key].configure.assert_called_with(state="disabled")

    def test_missing_button_no_crash(self, plugin):
        plugin._action_buttons = {}
        plugin._set_scan_buttons_state("normal")  # Should not raise
