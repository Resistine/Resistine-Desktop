"""Tests for plugins.antivirus.main — Plugin class logic methods.

Covers: check_status, _on_action routing, _handle_scan_complete,
_offer_quarantine_batch, destroy, status state mapping, and auto-update scheduler.
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
         patch("plugins.antivirus.main.settings") as mock_settings, \
         patch("platform.system", return_value="Darwin"):
        mock_settings.get.return_value = False
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
        for action_key in ("scan_file", "scan_directory",
                           "update_sigs", "whitelist_add"):
            with patch.object(plugin, "_start_file_scan" if action_key == "scan_file"
                              else "_start_directory_scan" if action_key == "scan_directory"
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
        for key in ("scan_file", "scan_directory"):
            plugin._action_buttons[key].configure.assert_called()

    def test_buttons_disabled_when_no_database(self, plugin):
        plugin._last_state = "no_database"
        result = ScanResult(target="/tmp/test", scanned=0)
        plugin._handle_scan_complete(result)
        for key in ("scan_file", "scan_directory"):
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

            plugin._offer_quarantine_batch({"/tmp/virus.exe": "Win.Trojan"})

            mock_clamav.quarantine_file.assert_called_once_with("/tmp/virus.exe")

    def test_user_declines(self, plugin):
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = False

            plugin._offer_quarantine_batch({"/tmp/virus.exe": "Win.Trojan"})

            mock_clamav.quarantine_file.assert_not_called()

    def test_quarantine_failure_logged(self, plugin):
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = True
            mock_clamav.quarantine_file.return_value = (False, "Permission denied")
            mock_clamav.list_quarantined.return_value = []

            plugin._offer_quarantine_batch({"/tmp/virus.exe": "Win.Trojan"})

            # Should still complete without raising
            mock_clamav.quarantine_file.assert_called_once()

    def test_truncates_long_listing(self, plugin):
        """Message shows first 20 files and '... and N more'."""
        infections = {f"/tmp/virus{i}.exe": f"Sig.{i}" for i in range(25)}
        with patch("plugins.antivirus.main.messagebox") as mock_mb, \
             patch("plugins.antivirus.main.clamav") as mock_clamav:
            mock_mb.askyesno.return_value = False
            plugin._offer_quarantine_batch(infections)
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
        plugin.main_container = MagicMock()

        with patch.object(plugin, "_stop_auto_update_scheduler") as mock_stop:
            plugin.destroy()
            mock_stop.assert_called_once()

        assert plugin._banner_frame is None
        assert plugin._banner_label is None
        assert plugin._banner_subtitle is None
        assert plugin._banner_action_btn is None
        assert plugin.main_container is None

    def test_destroy_no_main_frame(self, plugin):
        plugin.main_frame = None
        # Should not raise
        with patch.object(plugin, "_stop_auto_update_scheduler"):
            plugin.destroy()


# ---------------------------------------------------------------------------
# _toggle_auto_update
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestToggleAutoUpdate:
    def test_toggle_on_persists_and_starts_scheduler(self, plugin):
        plugin._auto_update_switch = MagicMock()
        plugin._auto_update_switch.get.return_value = True
        with patch("plugins.antivirus.main.settings") as mock_settings, \
             patch.object(plugin, "_start_auto_update_scheduler") as mock_start:
            plugin._toggle_auto_update()
            assert plugin._auto_update_on is True
            mock_settings.set.assert_called_once_with(
                "antivirus", "auto_update_enabled", True,
            )
            mock_start.assert_called_once()

    def test_toggle_off_persists_and_stops_scheduler(self, plugin):
        plugin._auto_update_switch = MagicMock()
        plugin._auto_update_switch.get.return_value = False
        with patch("plugins.antivirus.main.settings") as mock_settings, \
             patch.object(plugin, "_stop_auto_update_scheduler") as mock_stop:
            plugin._toggle_auto_update()
            assert plugin._auto_update_on is False
            mock_settings.set.assert_called_once_with(
                "antivirus", "auto_update_enabled", False,
            )
            mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# Auto-update scheduler
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAutoUpdateScheduler:
    def test_start_creates_daemon_thread(self, plugin):
        with patch("plugins.antivirus.main.threading") as mock_threading:
            mock_thread = MagicMock()
            mock_thread.is_alive.return_value = False
            mock_threading.Thread.return_value = mock_thread
            mock_threading.Event.return_value = MagicMock()

            plugin._auto_update_timer = None
            plugin._auto_update_stop = mock_threading.Event()
            plugin._start_auto_update_scheduler()

            mock_threading.Thread.assert_called_once_with(
                target=plugin._auto_update_loop, daemon=True,
            )
            mock_thread.start.assert_called_once()

    def test_start_skips_if_already_running(self, plugin):
        mock_timer = MagicMock()
        mock_timer.is_alive.return_value = True
        plugin._auto_update_timer = mock_timer

        with patch("plugins.antivirus.main.threading") as mock_threading:
            plugin._start_auto_update_scheduler()
            mock_threading.Thread.assert_not_called()

    def test_stop_sets_event_and_joins_thread(self, plugin):
        stop_event = MagicMock()
        mock_timer = MagicMock()
        plugin._auto_update_stop = stop_event
        plugin._auto_update_timer = mock_timer
        plugin._stop_auto_update_scheduler()
        stop_event.set.assert_called_once()
        mock_timer.join.assert_called_once_with(timeout=2)
        assert plugin._auto_update_timer is None

    def test_seconds_until_next_run_positive(self, plugin):
        delay = plugin._seconds_until_next_run()
        assert delay >= 60  # Floor of 1 minute
        # Should be within 24h + jitter (max ~26 hours)
        assert delay < 26 * 3600

    def test_auto_update_loop_calls_freshclam(self, plugin):
        """Verify the loop calls run_freshclam when the timer fires."""
        call_count = 0

        def fake_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return True  # Signal stop on second wait
            return False  # First wait "expires" — triggers freshclam

        plugin._auto_update_stop = MagicMock()
        plugin._auto_update_stop.is_set.return_value = False
        plugin._auto_update_stop.wait.side_effect = fake_wait
        plugin._auto_update_on = True
        plugin.app = MagicMock()

        with patch("plugins.antivirus.main.clamav") as mock_clamav, \
             patch.object(plugin, "_seconds_until_next_run", return_value=0):
            mock_clamav.run_freshclam.return_value = (True, "Updated")
            plugin._auto_update_loop()
            mock_clamav.run_freshclam.assert_called_once()


# ---------------------------------------------------------------------------
# _set_scan_buttons_state
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSetScanButtonsState:
    def test_enables_all(self, plugin):
        plugin._set_scan_buttons_state("normal")
        for key in ("scan_file", "scan_directory"):
            plugin._action_buttons[key].configure.assert_called_with(state="normal")

    def test_disables_all(self, plugin):
        plugin._set_scan_buttons_state("disabled")
        for key in ("scan_file", "scan_directory"):
            plugin._action_buttons[key].configure.assert_called_with(state="disabled")

    def test_missing_button_no_crash(self, plugin):
        plugin._action_buttons = {}
        plugin._set_scan_buttons_state("normal")  # Should not raise
