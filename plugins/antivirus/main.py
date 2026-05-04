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
from utils import settings
from utils.logger import logger

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))


def _send_notification(title: str, body: str):
    """Send a macOS system notification. No-op on other platforms."""
    import platform as _platform

    if _platform.system() != "Darwin":
        return
    try:
        from Foundation import NSUserNotification, NSUserNotificationCenter

        notification = NSUserNotification.alloc().init()
        notification.setTitle_(title)
        notification.setInformativeText_(body)
        notification.setSoundName_("default")
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        center.deliverNotification_(notification)
    except ImportError:
        # PyObjC not available — fall back to osascript
        import subprocess

        safe_body = body.replace("\\", "\\\\").replace('"', '\\"')
        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'display notification "{safe_body}" '
            f'with title "{safe_title}" sound name "default"'
        )
        try:
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


class Plugin(BasePlugin):
    """Antivirus plugin powered by ClamAV."""

    def __init__(self, app):
        super().__init__(
            id="012",
            version="2026.01.04-alpha",
            order=6,
            name="Antivirus",
            status=None,
            description="Scan, quarantine and protect against malware.",
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
        self._last_state = None
        self._last_status = None
        self._auto_update_timer = None
        self._auto_update_stop = threading.Event()
        self._init_ready = threading.Event()
        self.status = self.get_status()

        # Register system-level ClamAV daemons via SMAppService and refresh
        # system configs so post-Sparkle updates pick up any path changes.
        if platform.system() == "Darwin":
            def _darwin_daemon_init():
                clamav.ensure_daemons_registered()
                clamav.refresh_system_configs()
                self._init_ready.set()

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

    def _poll_initial_status(self):
        """Poll daemon state once so the sidebar shows the right icon."""
        self._init_ready.wait(timeout=10)
        try:
            status = clamav.get_realtime_status()
        except Exception:
            logger.debug("Antivirus: initial status poll failed")
            return
        self._last_state = status["state"]
        self._last_status = status
        self.status = self.check_status()

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

        # Show a development banner on Linux (Windows now wired up via Defender).
        if platform.system() == "Linux":
            banner = customtkinter.CTkFrame(
                self.main_frame,
                fg_color=("#FEF3C7", "#2D1F05"),
                corner_radius=10,
            )
            banner.grid(
                row=row, column=0, sticky="ew", padx=20, pady=(10, 0),
            )
            banner.grid_columnconfigure(0, weight=1)
            customtkinter.CTkLabel(
                banner,
                text=(
                    "Antivirus is not hooked up on Linux yet. "
                    "This UI is for development purposes only."
                ),
                font=customtkinter.CTkFont(family="Inter", size=12),
                text_color=("#92400E", "#FBBF24"),
                wraplength=600,
            ).grid(row=0, column=0, padx=16, pady=12)
            row += 1

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
        state = status["state"]
        self._last_state = state
        self._last_status = status
        self.status = self.check_status()
        self._apply_realtime_status_ui(status)
        self._schedule_status_poll()

    def _apply_realtime_status_ui(self, status: dict):
        """Update the status card widgets. Safe to call even if UI is gone."""
        if self._banner_frame is None:
            return

        try:
            if not self._banner_frame.winfo_exists():
                self._banner_frame = None
                return
        except Exception:
            self._banner_frame = None
            return

        state = status["state"]

        t = ThemeManager.theme.get("Theme", {})
        ok_bg = t.get("protection_bg_ok")
        ok_tx = t.get("protection_text_ok")
        warn_bg = t.get("protection_bg_warn")
        warn_tx = t.get("protection_text_warn")
        err_bg = t.get("status_badge_bg", {}).get("error")
        err_tx = t.get("status_badge_text", {}).get("error")

        # State-driven card configuration matching the VPN status card style
        states = {
            "not_installed": {
                "bg": err_bg,
                "title": "Not Installed",
                "title_color": err_tx,
                "subtitle": (
                    "ClamAV binaries were not found.\n"
                    "Reinstall Resistine or run the build script "
                    "to set up antivirus protection."
                ),
                "action": None,
            },
            "no_database": {
                "bg": warn_bg,
                "title": "Setup Required",
                "title_color": warn_tx,
                "subtitle": (
                    "No signature database found. "
                    "Tap Update Now below to download the latest "
                    "malware definitions before scanning."
                ),
                "action": None,
            },
            "protected": {
                "bg": ok_bg,
                "title": "Protected",
                "title_color": ok_tx,
                "subtitle": (
                    "Real-time malware protection is active"
                    if status.get("clamonacc_running")
                    else "On-demand scanning is active"
                ),
                "action": None,
            },
            "approval_required": {
                "bg": warn_bg,
                "title": "Approval Required",
                "title_color": warn_tx,
                "subtitle": (
                    "On-demand scanning is available. "
                    "Enable ClamAV daemons in System Settings "
                    "\u203A General \u203A Login Items "
                    "for faster scans and real-time protection."
                ),
                "action": ("Open Login Items", clamav.open_login_items_settings),
            },
            "fda_required": {
                "bg": warn_bg,
                "title": "Full Disk Access Required",
                "title_color": warn_tx,
                "subtitle": (
                    "Resistine needs Full Disk Access to monitor files "
                    "in real time. Grant access in System Settings "
                    "\u203A Privacy & Security \u203A Full Disk Access."
                ),
                "action": ("Open Settings", clamav.open_fda_settings),
            },
            "error": {
                "bg": err_bg,
                "title": "Protection Offline",
                "title_color": err_tx,
                "subtitle": (
                    "ClamAV daemons are not running"
                    if status.get("in_bundle")
                    else "On-demand scanning available. "
                    "Install Resistine.app for real-time protection."
                ),
                "action": (
                    ("Start Protection", self._start_protection)
                    if status.get("in_bundle")
                    else None
                ),
            },
        }

        cfg = states.get(state, states["error"])

        self._banner_frame.configure(fg_color=cfg["bg"])
        self._banner_label.configure(
            text=cfg["title"], text_color=cfg["title_color"],
        )
        self._banner_subtitle.configure(text=cfg["subtitle"])

        if cfg["action"]:
            label, handler = cfg["action"]
            self._banner_action_btn.configure(text=label, command=handler)
            self._banner_action_btn.grid()
        else:
            self._banner_action_btn.grid_remove()

        # Disable scan buttons when ClamAV can't actually scan
        can_scan = state not in ("not_installed", "no_database")
        self._set_scan_buttons_state("normal" if can_scan else "disabled")

    def _schedule_status_poll(self):
        """Schedule the next realtime status poll if the UI is still alive."""
        try:
            if hasattr(self, "main_frame") and self.main_frame.winfo_exists():
                self.app.after(10000, self._update_realtime_status)
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

    # ── System Daemon Activation ────────────────────────────────

    def _start_protection(self):
        """Start system-level ClamAV daemons (clamd + clamonacc)."""
        if self._banner_action_btn:
            self._banner_action_btn.configure(
                state="disabled", text="Starting...",
            )
        if self._banner_progress:
            self._banner_progress.grid()
            self._banner_progress.start()

        def _run():
            ok, msg = clamav.activate_system_daemons()
            self.app.after(0, self._handle_protection_started, ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _handle_protection_started(self, ok: bool, msg: str):
        if self._banner_progress:
            self._banner_progress.stop()
            self._banner_progress.grid_remove()
        if self._banner_action_btn:
            self._banner_action_btn.configure(
                state="normal", text="Start Protection",
            )
        if ok:
            self._update_realtime_status()
        else:
            self._log_append(f"Could not start protection: {msg}")
            logger.error(f"Antivirus: protection start failed: {msg}")

    # ── Action Router ─────────────────────────────────────────

    def _on_action(self, action_key: str):
        logger.info(f"Antivirus: action triggered — {action_key}")

        actions = {
            "scan_file": self._start_file_scan,
            "scan_directory": self._start_directory_scan,
            "scan_computer": self.full_computer_scan_placeholder,
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

    def full_computer_scan_placeholder(self):
        pass

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

        self._scan_handle = scan(
            target, on_progress=on_progress, on_complete=on_complete,
            on_total=on_total,
        )

    def _cancel_scan(self):
        """Cancel the running scan."""
        if self._scan_handle and not self._scan_handle.cancelled:
            self._scan_handle.cancel()
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
        self._scan_handle = None
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
            _send_notification(
                "Resistine — Threats Detected",
                f"{result.infected} infected file(s) found during scan.",
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
