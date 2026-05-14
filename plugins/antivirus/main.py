"""Antivirus plugin for Resistine Desktop.

Provides file/directory scanning, real-time protection, signature updates,
quarantine management, and whitelist via ClamAV binaries.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import platform
import random
import threading
import time
from tkinter import filedialog, messagebox

import customtkinter
from customtkinter import ThemeManager

from plugins.antivirus import clamav, threat_log
from plugins.antivirus.scanner import ScanResult, scan
from plugins.antivirus.theme import font
from plugins.antivirus.ui_builders import (
    build_scan_activity,
    build_scan_and_protection,
    build_status_banner,
)
from plugins.antivirus.ui_cards import (
    build_scan_exclusions,
    build_siem_card,
    build_updates_card,
    build_whitelist_and_quarantine,
)
from plugins.base_plugin import BasePlugin
from utils import notifications, settings
from utils.logger import logger

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))


class Plugin(BasePlugin):
    """Antivirus plugin powered by ClamAV."""

    def __init__(self, app):
        super().__init__(
            id="012",
            version="2026.01.04-alpha",
            order=6,
            name="Antivirus",
            status=None,
            description="Scan, quarantine, and protect against malware with ClamAV.",
            supported_systems=["Darwin", "Linux", "Windows"],
            translations={"US": "Antivirus", "ES": "Antivirus", "FR": "Antivirus"},
            icon_light_path=os.path.join(_PLUGIN_DIR, "antivirus_light.png"),
            icon_dark_path=os.path.join(_PLUGIN_DIR, "antivirus_dark.png"),
            uninstall_enabled=True,
        )
        self.app = app
        self._auto_update_on = settings.get(
            "antivirus", "auto_update_enabled", True,
        )
        self._action_buttons = {}
        self._banner_frame = None
        self._banner_label = None
        self._banner_subtitle = None
        self._banner_action_btn = None
        self._banner_progress = None
        self._scanning = False
        self._scan_handle = None
        self._scan_lock = threading.Lock()
        self._cancel_requested = False
        self._last_state = None
        self._last_status = None
        self._auto_update_timer = None
        self._auto_update_stop = threading.Event()
        self._rtd_watcher = None
        self._init_ready = threading.Event()
        self.status = self.get_status()

        # Register system-level ClamAV daemons via SMAppService, refresh
        # system configs, and resume any pending install via the state machine.
        if platform.system() == "Darwin":
            def _darwin_daemon_init():
                try:
                    clamav.ensure_daemons_registered()
                except Exception as exc:
                    logger.error(f"Antivirus: ensure_daemons_registered failed: {exc}")
                try:
                    clamav.refresh_system_configs()
                except Exception as exc:
                    logger.error(f"Antivirus: refresh_system_configs failed: {exc}")
                # Always set the event so the plugin doesn't hang
                self._init_ready.set()
                # Resume any pending ClamAV install
                from plugins.antivirus.installer_service import check_and_advance
                check_and_advance()

            threading.Thread(target=_darwin_daemon_init, daemon=True).start()
        else:
            self._init_ready.set()

        # Pre-start clamd so the signature DB is already loaded when the
        # user clicks scan. Without this, the first scan blocks for minutes
        # while clamd loads ~500 MB of signatures into memory.
        threading.Thread(target=self._ensure_clamd_warm, daemon=True).start()

        # Poll status once at startup so the sidebar icon shows the
        # correct state before the user clicks the Antivirus plugin.
        # Waits for daemon registration to finish first.
        threading.Thread(target=self._poll_initial_status, daemon=True).start()

        # Start the auto-update scheduler if enabled
        if self._auto_update_on:
            self._start_auto_update_scheduler()

    _INITIAL_POLL_RETRIES = 8  # up to ~16s of retries (8 × 2s)
    _INITIAL_POLL_INTERVAL = 2  # seconds between retries

    def _poll_initial_status(self):
        """Poll daemon state so the sidebar shows the right icon.

        After a fresh login, launchd may still be starting the ClamAV
        daemons. Retry a few times when the result is "offline" but
        setup is already completed — the daemons *should* be running
        but haven't started yet.
        """
        self._init_ready.wait(timeout=10)
        for attempt in range(1 + self._INITIAL_POLL_RETRIES):
            try:
                status = clamav.get_realtime_status()
            except Exception:
                logger.debug("Antivirus: initial status poll failed")
                return
            self._last_state = status["state"]
            self._last_status = status
            self.status = self.check_status()

            # If daemons are up (or setup isn't done yet), stop retrying
            if status.get("runtime_state") != "offline":
                return
            if status.get("setup_state") != "completed":
                return

            if attempt < self._INITIAL_POLL_RETRIES:
                logger.debug(
                    f"Antivirus: daemons offline on attempt {attempt + 1}, "
                    f"retrying in {self._INITIAL_POLL_INTERVAL}s",
                )
                time.sleep(self._INITIAL_POLL_INTERVAL)

    @staticmethod
    def _ensure_clamd_warm():
        """Start clamd if it isn't already running (and a DB exists)."""
        if clamav.is_clamd_running() or not clamav.has_database():
            return
        if not clamav.is_clamav_installed():
            return
        logger.info("Antivirus: pre-starting clamd for faster scans")
        ok, msg = clamav.start_clamd()
        if not ok:
            logger.warning(f"Antivirus: clamd warm-up failed: {msg}")

    def check_status(self):
        if self._last_state == "protected":
            return "OK"
        if self._last_state == "error":
            return "Error"
        return "Warning"

    # ── Main screen ──────────────────────────────────────────

    def create_main_screen(self):
        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent",
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(1, weight=0, minsize=100)
        self.main_container.grid_columnconfigure(2, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        self.main_frame = customtkinter.CTkScrollableFrame(
            self.main_container, corner_radius=0, fg_color="transparent",
        )
        self.main_frame.grid(row=0, column=1, sticky="nsew", pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)

        row = 0
        row = build_status_banner(self, self.main_frame, row)
        row = build_scan_and_protection(self, self.main_frame, row)
        row = build_scan_activity(self, self.main_frame, row)
        row = build_whitelist_and_quarantine(self, self.main_frame, row)
        row = build_scan_exclusions(self, self.main_frame, row)
        row = build_updates_card(self, self.main_frame, row)
        row = build_siem_card(self, self.main_frame, row)

        customtkinter.CTkLabel(
            self.main_frame, text="", height=12,
        ).grid(row=row, column=0)

        # Populate live data on screen creation
        self.app.after(100, self._refresh_db_info)
        self.app.after(200, self._refresh_whitelist)
        self.app.after(300, self._refresh_quarantine)
        self.app.after(400, self._refresh_exclusions)

        # If we already know the status from a previous poll, apply it
        # immediately so the card doesn't flash "Checking..." on every visit.
        # Then kick off the live poll after a short delay.
        if self._last_status is not None:
            self._apply_realtime_status_ui(self._last_status)
        self.app.after(500, self._update_realtime_status)

        MAX_CONTENT_WIDTH = 750
        _is_windows = platform.system() == "Windows"
        _resize_job = [None]

        def _do_layout():
            _resize_job[0] = None
            if (
                not hasattr(self, "main_container")
                or not self.main_container
                or not self.main_container.winfo_exists()
            ):
                return

            # --- Auto-hide Scrollbar Logic ---
            try:
                if hasattr(self.main_frame, "_parent_canvas") and hasattr(self.main_frame, "_scrollbar"):
                    yview = self.main_frame._parent_canvas.yview()
                    is_mapped = bool(self.main_frame._scrollbar.grid_info())
                    if yview and (yview[0] <= 0.01 and yview[1] >= 0.99):
                        if is_mapped:
                            self.main_frame._saved_sb_grid = self.main_frame._scrollbar.grid_info()
                            self.main_frame._scrollbar.grid_remove()
                    else:
                        if not is_mapped:
                            if hasattr(self.main_frame, "_saved_sb_grid") and self.main_frame._saved_sb_grid:
                                self.main_frame._scrollbar.grid(**self.main_frame._saved_sb_grid)
                            else:
                                self.main_frame._scrollbar.grid(row=0, column=1, sticky="ns", pady=0)
            except Exception:
                pass
            # --- End Auto-hide ---

            app_w = self.app.winfo_width()
            if app_w < 10:
                return
            try:
                nav = getattr(self.app, "navigation_frame", None)
                nav_w = nav.winfo_width() if (nav and nav.winfo_exists()) else 250
                nav_w = max(nav_w, 250)
            except Exception:
                nav_w = 250
            width = app_w - nav_w
            if width < 10:
                return
            breathing = 60 if _is_windows else 40
            if width > MAX_CONTENT_WIDTH + 40:
                col_w = MAX_CONTENT_WIDTH
            else:
                col_w = max(100, width - breathing)
            try:
                self.main_container.grid_columnconfigure(
                    1, weight=0, minsize=col_w,
                )
            except Exception:
                return

        def _on_resize(event):
            if _resize_job[0] is not None:
                try:
                    self.app.after_cancel(_resize_job[0])
                except Exception:
                    pass
            _resize_job[0] = self.app.after_idle(_do_layout)

        self.main_container.bind("<Configure>", _on_resize)
        self.app.after(50, _do_layout)

        return self.main_container

    def destroy(self):
        self._stop_auto_update_scheduler()
        self._stop_rtd_watcher()
        self._banner_frame = None
        self._banner_label = None
        self._banner_subtitle = None
        self._banner_action_btn = None
        self._banner_progress = None
        if hasattr(self, "main_container") and self.main_container:
            self.main_container.destroy()
            self.main_container = None

    # ── UI Event Handlers ────────────────────────────────────

    def _update_realtime_status(self):
        """Poll daemon state and update the banner."""
        def _check():
            try:
                status = clamav.get_realtime_status()
            except Exception:
                logger.debug("Antivirus: error during status poll")
                return
            try:
                self.app.after(0, self._apply_realtime_status, status)
            except Exception:
                logger.debug("Antivirus: app destroyed during status check")

        threading.Thread(target=_check, daemon=True).start()

    def _apply_realtime_status(self, status: dict):
        """Handle a fresh poll result: cache state, update UI, schedule next."""
        prev_setup = (
            self._last_status.get("setup_state") if self._last_status else None
        )
        state = status["state"]
        self._last_state = state
        self._last_status = status
        self.status = self.check_status()
        self._apply_realtime_status_ui(status)
        self._schedule_status_poll()
        # Refresh DB info when setup transitions to completed
        if status.get("setup_state") == "completed" and prev_setup != "completed":
            self._refresh_db_info()

        # Start/stop RTD watcher based on clamonacc state
        clamonacc_on = bool(status.get("clamonacc_running"))
        if clamonacc_on and self._rtd_watcher is None:
            self._start_rtd_watcher()
        elif not clamonacc_on and self._rtd_watcher is not None:
            self._stop_rtd_watcher()

    def _apply_realtime_status_ui(self, status: dict):
        """Update the status card widgets using two-dimensional state model.

        setup_state drives the UI during initial setup.
        runtime_state drives the UI after setup is complete.
        Safe to call even if UI is gone.
        """
        if self._banner_frame is None:
            return

        try:
            if not self._banner_frame.winfo_exists():
                self._banner_frame = None
                return
        except Exception:
            self._banner_frame = None
            return

        setup_state = status.get("setup_state", "completed")
        runtime_state = status.get("runtime_state", "offline")

        t = ThemeManager.theme.get("Theme", {})
        ok_bg = t.get("protection_bg_ok")
        ok_tx = t.get("protection_text_ok")
        warn_bg = t.get("protection_bg_warn")
        warn_tx = t.get("protection_text_warn")
        err_bg = t.get("status_badge_bg", {}).get("error")
        err_tx = t.get("status_badge_text", {}).get("error")

        is_linux = platform.system() == "Linux"
        cfg = None

        if not status.get("installed"):
            cfg = {
                "bg": err_bg, "title": "Not Installed", "title_color": err_tx,
                "subtitle": (
                    "ClamAV is not installed. Tap Install ClamAV to fetch "
                    "it from your distribution's package manager."
                    if is_linux else
                    "ClamAV binaries were not found.\n"
                    "Reinstall Resistine or run the build script "
                    "to set up antivirus protection."
                ),
                "action": (
                    ("Install ClamAV", self._start_system_setup)
                    if is_linux else None
                ),
            }
        elif setup_state != "completed":
            # Setup phase — derive from setup_state
            cfg = self._get_setup_banner_cfg(
                setup_state, status, ok_bg, ok_tx, warn_bg, warn_tx, err_bg, err_tx,
            )
        else:
            # Setup complete — derive from runtime_state
            cfg = self._get_runtime_banner_cfg(
                runtime_state, status, ok_bg, ok_tx, warn_bg, warn_tx, err_bg, err_tx,
            )

        self._banner_frame.configure(fg_color=cfg["bg"])
        self._banner_label.configure(
            text=cfg["title"], text_color=cfg["title_color"],
        )
        self._banner_subtitle.configure(text=cfg["subtitle"])

        # Show/hide progress bar based on active setup
        show_progress = setup_state in ("seeding_db", "installing")
        if self._banner_progress:
            if show_progress:
                self._banner_progress.grid()
                self._banner_progress.start()
            else:
                self._banner_progress.stop()
                self._banner_progress.grid_remove()

        if cfg["action"]:
            label, handler = cfg["action"]
            self._banner_action_btn.configure(
                text=label, command=handler, state="normal",
            )
            self._banner_action_btn.grid()
        else:
            self._banner_action_btn.grid_remove()

        # Disable scan buttons when ClamAV can't actually scan
        can_scan = status.get("installed") and status.get("db_present")
        self._set_scan_buttons_state("normal" if can_scan else "disabled")

        # Scan Computer is gated on real-time protection
        realtime_on = bool(status.get("clamonacc_running"))
        computer_btn = self._action_buttons.get("scan_computer")
        if computer_btn:
            computer_btn.configure(
                state="normal" if (can_scan and realtime_on) else "disabled",
            )

    def _get_setup_banner_cfg(
        self, setup_state, status, ok_bg, ok_tx, warn_bg, warn_tx, err_bg, err_tx,
    ) -> dict:
        """Return banner config for setup phase states."""
        if setup_state == "seeding_db":
            return {
                "bg": warn_bg, "title": "Downloading Definitions...",
                "title_color": warn_tx,
                "subtitle": "Downloading malware signature database. This may take a few minutes.",
                "action": None,
            }
        if setup_state == "seed_failed":
            from plugins.antivirus.installer_service import get_failure_reason

            reason = get_failure_reason()
            reason_text = {
                "dns_failed": "Could not reach the update server. Check your internet connection.",
                "network_timeout": "Download timed out. Check your internet connection.",
                "certs_missing": "Certificate verification failed. Try reinstalling Resistine.",
                "binary_missing": "ClamAV binaries not found. Reinstall Resistine.",
                "partial_download": "Download was incomplete. Tap Retry to try again.",
                "freshclam_failed": "Signature download failed. Tap Retry to try again.",
            }.get(reason, "Download failed. Tap Retry to try again.")
            return {
                "bg": err_bg, "title": "Download Failed",
                "title_color": err_tx, "subtitle": reason_text,
                "action": ("Retry", self._retry_setup),
            }
        if setup_state == "db_ready":
            return {
                "bg": warn_bg, "title": "Set Up Protection",
                "title_color": warn_tx,
                "subtitle": (
                    "Signature database downloaded. "
                    "Tap below to enable real-time protection "
                    "(requires administrator password)."
                ),
                "action": ("Set Up Protection", self._start_system_setup),
            }
        if setup_state == "installing":
            return {
                "bg": warn_bg, "title": "Setting Up...",
                "title_color": warn_tx,
                "subtitle": "Configuring system-level protection. This may take a moment.",
                "action": None,
            }
        if setup_state == "install_failed":
            from plugins.antivirus.installer_service import get_failure_reason

            reason = get_failure_reason()
            if reason == "user_canceled":
                subtitle = "Setup was cancelled. Tap Retry when ready."
            else:
                subtitle = "System setup failed. Tap Retry to try again."
            return {
                "bg": err_bg, "title": "Setup Failed",
                "title_color": err_tx, "subtitle": subtitle,
                "action": ("Retry", self._retry_setup),
            }
        # not_started — seed is about to begin automatically
        return {
            "bg": warn_bg, "title": "Starting Setup...",
            "title_color": warn_tx,
            "subtitle": "Preparing to download malware definitions...",
            "action": None,
        }

    @staticmethod
    def _get_runtime_banner_cfg(
        runtime_state, status, ok_bg, ok_tx, warn_bg, warn_tx, err_bg, err_tx,
    ) -> dict:
        """Return banner config for post-setup runtime states."""
        if runtime_state == "healthy":
            return {
                "bg": ok_bg, "title": "Protected", "title_color": ok_tx,
                "subtitle": (
                    "Real-time malware protection is active"
                    if status.get("clamonacc_running")
                    else "On-demand scanning is active"
                ),
                "action": None,
            }
        if runtime_state == "degraded":
            return {
                "bg": warn_bg, "title": "Protection Degraded",
                "title_color": warn_tx,
                "subtitle": (
                    "Scanning is available but real-time file monitoring "
                    "is not running. Full Disk Access may be needed."
                ),
                "action": ("Open Settings", clamav.open_fda_settings),
            }
        if runtime_state == "approval_required":
            return {
                "bg": warn_bg, "title": "Approval Required",
                "title_color": warn_tx,
                "subtitle": (
                    "Enable ClamAV daemons in System Settings "
                    "\u203A General \u203A Login Items "
                    "for real-time protection."
                ),
                "action": ("Open Login Items", clamav.open_login_items_settings),
            }
        if runtime_state == "fda_required":
            return {
                "bg": warn_bg, "title": "Full Disk Access Required",
                "title_color": warn_tx,
                "subtitle": (
                    "Resistine needs Full Disk Access to monitor files "
                    "in real time. Grant access in System Settings "
                    "\u203A Privacy & Security \u203A Full Disk Access."
                ),
                "action": ("Open Settings", clamav.open_fda_settings),
            }
        # offline
        is_linux = platform.system() == "Linux"
        return {
            "bg": err_bg, "title": "Protection Offline",
            "title_color": err_tx,
            "subtitle": (
                "ClamAV daemons are not running."
                if status.get("in_bundle")
                else (
                    "On-demand scanning available. "
                    "Enable systemd to start real-time protection."
                    if is_linux else
                    "On-demand scanning available. "
                    "Install Resistine.app for real-time protection."
                )
            ),
            "action": None,
        }

    def _schedule_status_poll(self):
        """Schedule the next realtime status poll if the UI is still alive.

        Polls faster (2s) during active setup so the UI doesn't look stuck.
        Normal interval (10s) after setup is complete.
        """
        try:
            if hasattr(self, "main_frame") and self.main_frame.winfo_exists():
                setup_active = self._last_status and self._last_status.get(
                    "setup_state", "completed",
                ) != "completed"
                interval = 2000 if setup_active else 10000
                self.app.after(interval, self._update_realtime_status)
        except Exception:
            logger.debug("Antivirus: could not schedule next status poll")

    def _toggle_auto_update(self):
        self._auto_update_on = bool(self._auto_update_switch.get())
        settings.set("antivirus", "auto_update_enabled", self._auto_update_on)
        logger.info(
            f"Antivirus: auto-update toggled "
            f"{'on' if self._auto_update_on else 'off'}",
        )
        if self._auto_update_on:
            self._start_auto_update_scheduler()
        else:
            self._stop_auto_update_scheduler()

    # ── Real-Time Detection Watcher ─────────────────────────────

    def _get_clamd_log_path(self) -> str:
        sys_dir = getattr(clamav, "_SYSTEM_LOG_DIR", None)
        if sys_dir:
            system_log = os.path.join(sys_dir, "clamd.log")
            if os.path.isfile(system_log):
                return system_log
        return os.path.join(clamav._LOG_DIR, "clamd.log")

    def _start_rtd_watcher(self):
        from plugins.antivirus.rtd_watcher import ClamdLogWatcher

        log_path = self._get_clamd_log_path()
        self._rtd_watcher = ClamdLogWatcher(
            log_path, self._on_rtd_threat, self._on_rtd_summary,
        )
        self._rtd_watcher.start()
        logger.info(f"Antivirus: RTD watcher started on {log_path}")

    def _stop_rtd_watcher(self):
        if self._rtd_watcher is not None:
            self._rtd_watcher.stop()
            self._rtd_watcher = None
            logger.info("Antivirus: RTD watcher stopped")

    def _on_rtd_threat(self, filepath: str, signature: str):
        # threat_log.log_threat_detected is already called by the watcher
        # (for both notified and rate-limited detections); don't double-log.
        try:
            self.app.after(0, self._handle_rtd_on_main, filepath, signature)
        except Exception:
            pass  # app destroyed

    def _on_rtd_summary(self, count: int):
        try:
            self.app.after(0, self._handle_rtd_summary_on_main, count)
        except Exception:
            pass

    def _handle_rtd_on_main(self, filepath: str, signature: str):
        basename = os.path.basename(filepath)
        notifications.send(
            "Resistine \u2014 Threat Blocked",
            f"Malware detected: {signature}\n{basename}",
            urgency="critical",
        )

    def _handle_rtd_summary_on_main(self, count: int):
        notifications.send(
            "Resistine \u2014 Threat Blocked",
            f"{count} additional threat(s) detected",
            urgency="critical",
        )

    # ── Auto-Update Scheduler ─────────────────────────────────

    _AUTO_UPDATE_HOUR = 4  # Target hour (4:00 AM)
    _AUTO_UPDATE_JITTER_SECS = 7200  # ±2 hours

    def _start_auto_update_scheduler(self):
        """Start the background thread that triggers freshclam daily."""
        if self._auto_update_timer and self._auto_update_timer.is_alive():
            return
        # Fresh event per thread to avoid races with a previous thread
        self._auto_update_stop = threading.Event()
        self._auto_update_timer = threading.Thread(
            target=self._auto_update_loop, daemon=True,
        )
        self._auto_update_timer.start()
        logger.info("Antivirus: auto-update scheduler started")

    def _stop_auto_update_scheduler(self):
        """Signal the scheduler thread to stop and wait for it to exit."""
        self._auto_update_stop.set()
        timer = self._auto_update_timer
        if timer is not None:
            timer.join(timeout=2)
        self._auto_update_timer = None
        logger.info("Antivirus: auto-update scheduler stopped")

    def _seconds_until_next_run(self) -> float:
        """Calculate seconds until the next 4 AM (±2 hr jitter)."""
        now = time.time()
        local = time.localtime(now)
        # Build today's target time
        target = time.mktime((
            local.tm_year, local.tm_mon, local.tm_mday,
            self._AUTO_UPDATE_HOUR, 0, 0,
            local.tm_wday, local.tm_yday, local.tm_isdst,
        ))
        # Roll to tomorrow first if today's 4 AM already passed
        if target <= now:
            target += 86400
        # Apply jitter after rollover so the base is always "next 4 AM"
        jitter = random.randint(
            -self._AUTO_UPDATE_JITTER_SECS,
            self._AUTO_UPDATE_JITTER_SECS,
        )
        return max(60, (target - now) + jitter)

    def _auto_update_loop(self):
        """Background loop: sleep until next run, then call freshclam."""
        while not self._auto_update_stop.is_set():
            delay = self._seconds_until_next_run()
            logger.info(
                f"Antivirus: next auto-update in "
                f"{delay / 3600:.1f} hours",
            )
            # Sleep in short intervals so we can exit promptly
            if self._auto_update_stop.wait(timeout=delay):
                break
            if not self._auto_update_on:
                break
            logger.info("Antivirus: running scheduled signature update")
            ok, msg = clamav.run_freshclam()
            if ok:
                logger.info(f"Antivirus: auto-update succeeded — {msg}")
            else:
                logger.warning(f"Antivirus: auto-update failed — {msg}")
            # Refresh the UI if it's visible
            try:
                self.app.after(0, self._refresh_db_info)
            except Exception:
                logger.debug("Antivirus: app destroyed during auto-update")

    # ── Scan Log Helpers ──────────────────────────────────────

    def _log_append(self, text: str):
        """Append a line to the scan activity textbox.

        Must be called on the main thread — use app.after() from workers.
        """
        self._scan_log.configure(state="normal")
        self._scan_log.insert("end", text + "\n")
        self._scan_log.see("end")
        self._scan_log.configure(state="disabled")

    def _log_clear(self):
        self._scan_log.configure(state="normal")
        self._scan_log.delete("1.0", "end")
        self._scan_log.configure(state="disabled")

    def _set_scan_buttons_state(self, state: str):
        for key in ("scan_file", "scan_directory"):
            btn = self._action_buttons.get(key)
            if btn:
                btn.configure(state=state)
        # scan_computer is gated separately on real-time protection — only
        # re-enable it if the last poll said clamonacc is running.
        computer_btn = self._action_buttons.get("scan_computer")
        if computer_btn:
            realtime_on = bool(
                self._last_status and self._last_status.get("clamonacc_running"),
            )
            if state == "disabled":
                computer_btn.configure(state="disabled")
            else:
                computer_btn.configure(
                    state="normal" if realtime_on else "disabled",
                )

    # ── System Daemon Activation ────────────────────────────────

    def _start_system_setup(self):
        """Launch the ClamAV postinstall script via the installer service."""
        from plugins.antivirus.installer_service import trigger_system_setup

        if self._banner_action_btn:
            self._banner_action_btn.configure(
                state="disabled", text="Starting...",
            )

        def _run():
            ok = trigger_system_setup()
            if ok:
                self.app.after(0, self._poll_setup_progress)
            else:
                self.app.after(0, self._update_realtime_status)

        threading.Thread(target=_run, daemon=True).start()

    def _retry_setup(self):
        """Manual retry — reset backoff and restart the current phase."""
        from plugins.antivirus.installer_service import retry

        if self._banner_action_btn:
            self._banner_action_btn.configure(state="disabled", text="Retrying...")

        def _run():
            retry()
            self.app.after(0, self._update_realtime_status)

        threading.Thread(target=_run, daemon=True).start()

    _MAX_SETUP_POLLS = 100  # ~5 min at 3s intervals

    def _poll_setup_progress(self):
        """Poll the postinstall status file every 3 seconds."""
        from plugins.antivirus.installer_service import poll_setup_progress

        def _check():
            result = poll_setup_progress()
            try:
                self.app.after(0, self._handle_setup_poll, result)
            except Exception:
                pass  # App destroyed

        threading.Thread(target=_check, daemon=True).start()

    def _handle_setup_poll(self, result: dict):
        """Handle a setup progress poll result."""
        if result["finished"]:
            self._setup_poll_count = 0
            self._update_realtime_status()
            if result["success"]:
                logger.info("Antivirus: system setup completed")
                self._refresh_db_info()
            else:
                self._log_append(f"Setup error: {result.get('error', 'unknown')}")
                logger.error(f"Antivirus: setup failed: {result.get('error')}")
            return

        # Still running — update step label and poll again
        self._setup_poll_count = getattr(self, "_setup_poll_count", 0) + 1
        if self._setup_poll_count >= self._MAX_SETUP_POLLS:
            logger.error("Antivirus: setup poll exceeded max attempts")
            self._setup_poll_count = 0
            self._update_realtime_status()
            return

        step = result.get("step", "")
        try:
            if (
                step
                and self._banner_subtitle
                and self._banner_subtitle.winfo_exists()
            ):
                step_labels = {
                    "create_dirs": "Creating system directories...",
                    "write_configs": "Writing configuration files...",
                    "set_permissions": "Setting permissions...",
                    "seed_db": "Copying signature database...",
                    "cleanup_legacy": "Cleaning up legacy daemons...",
                    "load_daemons": "Loading daemons...",
                }
                label = step_labels.get(step, f"Running: {step}...")
                self._banner_subtitle.configure(text=label)
        except Exception:
            pass  # Widget destroyed

        # Schedule next poll
        try:
            if hasattr(self, "main_frame") and self.main_frame.winfo_exists():
                self.app.after(3000, self._poll_setup_progress)
        except Exception:
            pass

    # ── Action Router ─────────────────────────────────────────

    def _on_action(self, action_key: str):
        logger.info(f"Antivirus: action triggered — {action_key}")

        actions = {
            "scan_file": self._start_file_scan,
            "scan_directory": self._start_directory_scan,
            "scan_computer": self._start_computer_scan,
            "update_sigs": self._start_sig_update,
            "whitelist_add": self._add_whitelist_entry,
        }
        handler = actions.get(action_key)
        if handler:
            handler()

    # ── File / Directory Scan ─────────────────────────────────

    def _start_file_scan(self):
        if self._scanning:
            return
        path = filedialog.askopenfilename(
            title="Select File to Scan", parent=self.app,
        )
        if not path:
            return
        if clamav.is_path_whitelisted(path):
            messagebox.showinfo(
                "Whitelisted",
                f"'{os.path.basename(path)}' is inside a whitelisted "
                "location and will not be scanned.\n\n"
                "Remove it from the whitelist first to scan.",
                parent=self.app,
            )
            return
        self._run_scan(path)

    def _start_directory_scan(self):
        if self._scanning:
            return
        path = filedialog.askdirectory(
            title="Select Directory to Scan", parent=self.app,
        )
        if not path:
            return
        if clamav.is_path_whitelisted(path):
            messagebox.showinfo(
                "Whitelisted",
                f"'{os.path.basename(path)}' is whitelisted and will "
                "not be scanned.\n\n"
                "Remove it from the whitelist first to scan.",
                parent=self.app,
            )
            return
        self._run_scan(path)

    def _computer_scan_targets(self) -> list[str]:
        """Return the fixed list of directories scanned by 'Scan Computer'.

        Picks user-data and app dirs that exist on disk and aren't
        whitelisted. Skips system roots that would balloon scan time
        (/System on macOS, C:\\Windows on Windows) — clamonacc handles
        real-time coverage there.
        """
        system = platform.system()
        home = os.path.expanduser("~")
        if system == "Darwin":
            candidates = [
                home,
                "/Applications",
                "/Library/LaunchAgents",
                "/Library/LaunchDaemons",
                "/usr/local/bin",
                "/opt/homebrew/bin",
                "/tmp",
            ]
        elif system == "Windows":
            candidates = [
                home,
                os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                os.environ.get("TEMP", r"C:\Windows\Temp"),
            ]
        else:  # Linux / other POSIX
            candidates = [
                home,
                "/opt",
                "/usr/local/bin",
                "/tmp",
            ]
        targets = []
        for path in candidates:
            if not path or not os.path.isdir(path):
                continue
            if clamav.is_path_whitelisted(path):
                continue
            targets.append(path)
        return targets

    def _start_computer_scan(self):
        """Scan a fixed set of directories (Documents, Applications, etc.)."""
        if self._scanning:
            return
        targets = self._computer_scan_targets()
        if not targets:
            messagebox.showinfo(
                "Nothing to Scan",
                "No scannable directories found. Check your whitelist.",
                parent=self.app,
            )
            return
        self._run_multi_scan(targets)

    def _run_multi_scan(self, targets: list[str]):
        """Run scans on multiple targets sequentially, aggregating results."""
        self._scanning = True
        self._cancel_requested = False
        self._set_scan_buttons_state("disabled")
        self._log_clear()

        self._scan_progress.grid()
        self._scan_progress.configure(mode="indeterminate")
        self._scan_progress.start()

        cancel_btn = self._action_buttons.get("cancel_scan")
        if cancel_btn:
            cancel_btn.grid()

        self._log_append(
            f"Scanning computer ({len(targets)} location"
            f"{'s' if len(targets) != 1 else ''})...",
        )
        for t in targets:
            self._log_append(f"  • {t}")

        # Cumulative counters across all targets
        agg = {
            "scanned": 0,
            "infected": 0,
            "infections": [],
            "files_seen": 0,
            "total_files": 0,
            "cancelled": False,
        }

        def _worker():
            for idx, target in enumerate(targets, 1):
                if agg["cancelled"] or self._cancel_requested:
                    agg["cancelled"] = True
                    break
                self.app.after(
                    0, self._on_multi_scan_target_start, idx, len(targets), target,
                )
                # Visibility: $HOME and similar large dirs spend 30s–2min in
                # _walk_files before scan_path emits anything. Print the
                # target so the UI doesn't look frozen during the walk.
                self.app.after(
                    0, self._log_append,
                    f"[{idx}/{len(targets)}] Indexing {target}...",
                )
                done = threading.Event()
                target_total = [0]

                def on_total(total: int, _t=target_total):
                    _t[0] = total
                    self.app.after(
                        0, self._on_scan_total_known_multi, total, agg,
                    )

                def on_progress(line: str):
                    self.app.after(0, self._log_append, line)
                    if ":" in line and ("OK" in line or "FOUND" in line):
                        agg["files_seen"] += 1
                        total = agg["total_files"]
                        if total > 0:
                            status = (
                                f"Scanned {agg['files_seen']} / {total} files"
                            )
                            pct = agg["files_seen"] / total
                        else:
                            status = f"Scanned {agg['files_seen']} files"
                            pct = None
                        self.app.after(
                            0, self._on_scan_file_done, status, pct,
                        )

                def on_complete(result: ScanResult):
                    if result.error and "cancelled" in result.error.lower():
                        agg["cancelled"] = True
                    elif result.error:
                        # Don't abort the whole sweep on a single-dir error;
                        # log it and move on.
                        self.app.after(
                            0, self._log_append,
                            f"Error scanning {result.target}: {result.error}",
                        )
                    else:
                        agg["scanned"] += result.scanned
                        agg["infected"] += result.infected
                        agg["infections"].extend(result.infections)
                    done.set()

                handle = scan(
                    target,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    on_total=on_total,
                )
                with self._scan_lock:
                    self._scan_handle = handle
                done.wait()
                with self._scan_lock:
                    self._scan_handle = None

            final = ScanResult(
                target="Computer",
                scanned=agg["scanned"],
                infected=agg["infected"],
                infections=agg["infections"],
                error="Scan cancelled." if agg["cancelled"] else "",
            )
            self.app.after(0, self._handle_scan_complete, final)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_multi_scan_target_start(
        self, idx: int, total: int, target: str,
    ):
        """Update the status label as each directory in the sweep starts."""
        short = os.path.basename(target.rstrip(os.sep)) or target
        self._scan_status_label.configure(
            text=f"[{idx}/{total}] Scanning: {short}",
        )

    def _on_scan_total_known_multi(self, total: int, agg: dict):
        """Add this directory's file count to the aggregate progress total."""
        agg["total_files"] += total
        if agg["total_files"] > 0:
            self._scan_progress.stop()
            self._scan_progress.configure(mode="determinate")
            if agg["files_seen"] > 0:
                self._scan_progress.set(
                    min(agg["files_seen"] / agg["total_files"], 1.0),
                )
            else:
                self._scan_progress.set(0)

    def _run_scan(self, target: str):
        self._scanning = True
        self._set_scan_buttons_state("disabled")
        self._log_clear()

        self._scan_progress.grid()
        self._scan_progress.configure(mode="indeterminate")
        self._scan_progress.start()

        # Show cancel button
        cancel_btn = self._action_buttons.get("cancel_scan")
        if cancel_btn:
            cancel_btn.grid()

        short = os.path.basename(target) or target
        self._scan_status_label.configure(text=f"Scanning: {short}")
        self._log_append(f"Scanning: {target}")

        file_count = [0]
        total_files = [0]

        def on_total(total: int):
            total_files[0] = total
            self.app.after(0, self._on_scan_total_known, total)

        def on_progress(line: str):
            self.app.after(0, self._log_append, line)
            if ":" in line and ("OK" in line or "FOUND" in line):
                file_count[0] += 1
                total = total_files[0]
                if total > 0:
                    status = f"Scanned {file_count[0]} / {total} files"
                    pct = file_count[0] / total
                else:
                    status = f"Scanned {file_count[0]} files"
                    pct = None
                self.app.after(
                    0, self._on_scan_file_done, status, pct,
                )

        def on_complete(result: ScanResult):
            self.app.after(0, self._handle_scan_complete, result)

        with self._scan_lock:
            self._scan_handle = scan(
                target, on_progress=on_progress, on_complete=on_complete,
                on_total=on_total,
            )

    def _cancel_scan(self):
        """Cancel the running scan."""
        # Set the multi-scan cancel flag first so the worker loop won't
        # start the next directory even if the click lands between targets
        # (when self._scan_handle is briefly None).
        self._cancel_requested = True
        with self._scan_lock:
            handle = self._scan_handle
        if handle and not handle.cancelled:
            handle.cancel()
        self._log_append("Cancelling scan...")
        cancel_btn = self._action_buttons.get("cancel_scan")
        if cancel_btn:
            cancel_btn.configure(state="disabled")

    def _on_scan_total_known(self, total: int):
        """Switch progress bar to determinate mode when file count is known."""
        self._scan_progress.stop()
        if total == 0:
            self._scan_progress.grid_remove()
            self._scan_status_label.configure(text="No files matched filters")
            return
        self._scan_progress.configure(mode="determinate")
        self._scan_progress.set(0)

    def _on_scan_file_done(self, status: str, pct: float | None):
        """Update scan progress label and bar after each file."""
        self._scan_status_label.configure(text=status)
        if pct is not None:
            self._scan_progress.set(min(pct, 1.0))

    def _handle_scan_complete(self, result: ScanResult):
        self._scanning = False
        with self._scan_lock:
            self._scan_handle = None
        self._cancel_requested = False
        self._scan_progress.stop()
        self._scan_progress.set(1.0 if not result.error else 0)
        self._scan_progress.configure(mode="determinate")
        self._scan_progress.grid_remove()

        # Re-enable scan buttons only if ClamAV is in a scannable state
        can_scan = self._last_state not in ("not_installed", "no_database")
        self._set_scan_buttons_state("normal" if can_scan else "disabled")

        # Hide cancel button and reset its state for next scan
        cancel_btn = self._action_buttons.get("cancel_scan")
        if cancel_btn:
            cancel_btn.configure(state="normal")
            cancel_btn.grid_remove()

        if result.error:
            if "cancelled" in result.error.lower():
                self._scan_status_label.configure(text="Scan cancelled")
                self._log_append("Scan cancelled.")
            else:
                self._scan_status_label.configure(text="Scan failed")
                self._log_append(f"Error: {result.error}")
            return

        self._log_append(
            f"Done — {result.scanned} files scanned, "
            f"{result.infected} infected",
        )
        if result.duration:
            self._log_append(f"Time: {result.duration}")

        if result.infected > 0:
            self._scan_status_label.configure(
                text=f"Threats found: {result.infected}",
            )
            notifications.send(
                "Resistine — Threats Detected",
                f"{result.infected} infected file(s) found during scan.",
                urgency="critical",
            )
            infections: dict[str, str] = {}
            for infection_line in result.infections:
                filepath, sig = threat_log.parse_infection_line(
                    infection_line,
                )
                infections[filepath] = sig
                threat_log.log_threat_detected(sig, filepath)
            if infections:
                self._offer_quarantine_batch(infections)
        else:
            self._scan_status_label.configure(text="No threats found")

    def _offer_quarantine_batch(self, infections: dict[str, str]):
        """Ask user whether to quarantine all infected files.

        infections: dict mapping filepath -> ClamAV signature name.
        """
        filepaths = list(infections)
        names = [os.path.basename(p) for p in filepaths]
        listing = "\n".join(f"  \u2022 {n}" for n in names[:20])
        if len(names) > 20:
            listing += f"\n  ... and {len(names) - 20} more"

        answer = messagebox.askyesno(
            "Threats Detected",
            f"{len(filepaths)} infected file(s) found:\n\n"
            f"{listing}\n\nMove all to quarantine?",
            parent=self.app,
        )
        if not answer:
            return

        quarantined = 0
        for filepath in filepaths:
            ok, dest = clamav.quarantine_file(filepath)
            basename = os.path.basename(filepath)
            if ok:
                self._log_append(f"Quarantined: {basename}")
                threat_log.log_threat_quarantined(
                    infections[filepath], filepath, dest,
                )
                quarantined += 1
            else:
                self._log_append(f"Quarantine failed ({basename}): {dest}")
        self._refresh_quarantine()
        self._log_append(
            f"Quarantined {quarantined}/{len(filepaths)} files",
        )

    # ── Signature Updates ─────────────────────────────────────

    def _start_sig_update(self):
        btn = self._action_buttons.get("update_sigs")
        if btn:
            btn.configure(state="disabled", text="Updating...")

        self._log_clear()
        self._log_append("Updating signature database...")
        self._scan_status_label.configure(text="Updating signatures...")

        def _run():
            def on_line(line):
                self.app.after(0, self._log_append, line)

            ok, msg = clamav.run_freshclam(on_line=on_line)
            self.app.after(0, self._handle_update_complete, ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _handle_update_complete(self, ok: bool, msg: str):
        btn = self._action_buttons.get("update_sigs")
        if btn:
            btn.configure(state="normal", text="Update Now")

        self._log_append(msg)
        if ok:
            self._scan_status_label.configure(text="Signatures updated")
        else:
            self._scan_status_label.configure(text="Update failed")

        self._refresh_db_info()

    def _refresh_db_info(self):
        """Update the Signature Updates card with live DB info."""
        info = clamav.get_db_info()
        labels = getattr(self, "_db_labels", {})
        if "Signatures" in labels:
            labels["Signatures"].configure(text=info["signatures"])
        if "Last Updated" in labels:
            labels["Last Updated"].configure(text=info["last_updated"])

    # ── Whitelist ──────────────────────────────────────────────

    def _add_whitelist_entry(self):
        path = filedialog.askdirectory(
            title="Select Folder to Whitelist", parent=self.app,
        )
        if not path:
            return
        clamav.add_to_whitelist(path)
        self._refresh_whitelist()

    def _refresh_whitelist(self):
        """Rebuild the whitelist card contents."""
        frame = getattr(self, "_whitelist_frame", None)
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()

        entries = clamav.get_whitelist()
        if not entries:
            customtkinter.CTkLabel(
                frame, text="No whitelisted paths",
                font=font(12),
                text_color=ThemeManager.theme.get("Theme", {}).get(
                    "text_secondary",
                ),
            ).grid(row=0, column=0, sticky="w")
            return

        for i, entry in enumerate(entries):
            row_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
            row_frame.grid(row=i, column=0, sticky="ew", pady=1)
            row_frame.grid_columnconfigure(0, weight=1)

            customtkinter.CTkLabel(
                row_frame, text=os.path.basename(entry) or entry,
                font=font(11), anchor="w",
            ).grid(row=0, column=0, sticky="w")

            customtkinter.CTkButton(
                row_frame, text="\u2715", width=24, height=24,
                font=font(10), fg_color="transparent",
                hover_color=("#E5E7EB", "#2A2A2C"),
                command=lambda p=entry: self._remove_whitelist(p),
            ).grid(row=0, column=1, sticky="e")

    def _remove_whitelist(self, path: str):
        clamav.remove_from_whitelist(path)
        self._refresh_whitelist()

    # ── Scan Exclusions ───────────────────────────────────────

    def _add_excluded_extension(self):
        """Add extension(s) from the entry field."""
        raw = self._ext_entry.get().strip()
        if not raw:
            return
        exts = [part.strip() for part in raw.split(",") if part.strip()]
        if exts:
            clamav.add_excluded_extensions(exts)
        self._ext_entry.delete(0, "end")
        self._refresh_exclusions()

    def _remove_excluded_extension(self, ext: str):
        clamav.remove_excluded_extension(ext)
        self._refresh_exclusions()

    def _save_max_file_size(self):
        """Persist the max file size from the entry field."""
        raw = self._size_entry.get().strip()
        try:
            size = int(raw) if raw else 0
            size = max(0, min(size, 10000))  # Clamp 0–10 GB
        except ValueError:
            size = 0
        clamav.set_max_file_size(size)
        self._size_entry.delete(0, "end")
        self._size_entry.insert(0, str(size))

    def _refresh_exclusions(self):
        """Rebuild the scan exclusions card contents."""
        frame = getattr(self, "_exclusions_frame", None)
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()

        excl = clamav.get_scan_exclusions()

        if not excl["extensions"]:
            customtkinter.CTkLabel(
                frame, text="No excluded extensions",
                font=font(12),
                text_color=ThemeManager.theme.get("Theme", {}).get(
                    "text_secondary",
                ),
            ).grid(row=0, column=0, sticky="w")
        else:
            for i, ext in enumerate(excl["extensions"]):
                row_frame = customtkinter.CTkFrame(
                    frame, fg_color="transparent",
                )
                row_frame.grid(row=i, column=0, sticky="ew", pady=1)
                row_frame.grid_columnconfigure(0, weight=1)

                customtkinter.CTkLabel(
                    row_frame, text=ext, font=font(11), anchor="w",
                ).grid(row=0, column=0, sticky="w")

                customtkinter.CTkButton(
                    row_frame, text="\u2715", width=24, height=24,
                    font=font(10), fg_color="transparent",
                    hover_color=("#E5E7EB", "#2A2A2C"),
                    command=lambda e=ext: self._remove_excluded_extension(e),
                ).grid(row=0, column=1, sticky="e")

        size_entry = getattr(self, "_size_entry", None)
        if size_entry:
            size_entry.delete(0, "end")
            size_entry.insert(0, str(excl["max_size_mb"]))

    # ── SIEM Forwarding ───────────────────────────────────────

    def _setup_wazuh_forwarding(self):
        """Configure Wazuh agent to forward threat logs."""
        btn = getattr(self, "_siem_btn", None)
        if btn:
            btn.configure(state="disabled", text="Configuring...")

        def _run():
            ok, msg = threat_log.setup_wazuh_forwarding()
            self.app.after(0, self._handle_wazuh_setup, ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _handle_wazuh_setup(self, ok: bool, msg: str):
        if not hasattr(self, "main_frame") or not self.main_frame:
            return
        btn = getattr(self, "_siem_btn", None)
        lbl = getattr(self, "_siem_status_label", None)
        if ok:
            self._log_append(f"SIEM: {msg}")
            if btn:
                btn.configure(text="Configured", state="disabled")
            if lbl:
                lbl.configure(text="Forwarding active")
        else:
            self._log_append(f"SIEM setup failed: {msg}")
            if btn:
                btn.configure(state="normal", text="Configure Forwarding")

    # ── Quarantine ─────────────────────────────────────────────

    def _refresh_quarantine(self):
        """Rebuild the quarantine card contents."""
        frame = getattr(self, "_quarantine_frame", None)
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()

        entries = clamav.list_quarantined()
        if not entries:
            customtkinter.CTkLabel(
                frame, text="No threats quarantined",
                font=font(12),
                text_color=ThemeManager.theme.get("Theme", {}).get(
                    "text_secondary",
                ),
            ).grid(row=0, column=0, sticky="w")
            return

        for i, qpath in enumerate(entries):
            name = os.path.basename(qpath).replace(".quarantined", "")
            row_frame = customtkinter.CTkFrame(frame, fg_color="transparent")
            row_frame.grid(row=i, column=0, sticky="ew", pady=1)
            row_frame.grid_columnconfigure(0, weight=1)

            customtkinter.CTkLabel(
                row_frame, text=name, font=font(11), anchor="w",
            ).grid(row=0, column=0, sticky="w")

            customtkinter.CTkButton(
                row_frame, text="Restore", width=50, height=22,
                font=font(10), fg_color="transparent",
                hover_color=("#DBEAFE", "#1E2A3A"),
                text_color=("#2563EB", "#60A5FA"),
                command=lambda p=qpath: self._restore_quarantined(p),
            ).grid(row=0, column=1, sticky="e", padx=(4, 0))

            customtkinter.CTkButton(
                row_frame, text="Delete", width=50, height=22,
                font=font(10), fg_color="transparent",
                hover_color=("#FEE2E2", "#3B1010"),
                text_color=("#DC2626", "#F87171"),
                command=lambda p=qpath: self._delete_quarantined(p),
            ).grid(row=0, column=2, sticky="e", padx=(4, 0))

    def _restore_quarantined(self, qpath: str):
        name = os.path.basename(qpath).replace(".quarantined", "")
        dest = filedialog.askdirectory(
            title=f"Restore '{name}' to...", parent=self.app,
        )
        if not dest:
            return
        target = os.path.join(dest, name)
        ok, msg = clamav.restore_quarantined(qpath, target)
        if ok:
            self._refresh_quarantine()
        else:
            messagebox.showerror("Restore Failed", msg, parent=self.app)

    def _delete_quarantined(self, qpath: str):
        name = os.path.basename(qpath).replace(".quarantined", "")
        if messagebox.askyesno(
            "Delete Quarantined File",
            f"Permanently delete '{name}'?",
            parent=self.app,
        ):
            clamav.delete_quarantined(qpath)
            threat_log.log_threat_deleted(name)
            self._refresh_quarantine()
