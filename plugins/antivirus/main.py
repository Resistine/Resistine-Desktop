"""Antivirus plugin for Resistine Desktop.

Provides file/directory scanning, real-time protection, signature updates,
quarantine management, and whitelist via ClamAV binaries.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import random
import threading
import time
from tkinter import filedialog, messagebox

import customtkinter

from plugins.antivirus import clamav
from plugins.antivirus.scanner import ScanResult, scan
from plugins.antivirus.theme import (
    COLOR_ERR_BG,
    COLOR_ERR_TEXT,
    COLOR_MUTED,
    COLOR_OK_BG,
    COLOR_OK_TEXT,
    COLOR_WARN_BG,
    COLOR_WARN_TEXT,
    font,
)
from plugins.antivirus.ui_builders import (
    build_scan_activity,
    build_scan_and_protection,
    build_status_banner,
)
from plugins.antivirus.ui_cards import (
    build_updates_card,
    build_whitelist_and_quarantine,
)
from plugins.base_plugin import BasePlugin
from utils import settings
from utils.logger import logger

_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))

# Neutral grey for first-time setup states (matches VPN "No Configuration")
_COLOR_SETUP_BG = ("#F5F5F5", "#1A1A1A")
_COLOR_SETUP_TEXT = ("#666666", "#999999")


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
        import platform
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
        self.main_frame = customtkinter.CTkScrollableFrame(
            self.app, corner_radius=0, fg_color="transparent",
        )
        self.main_frame.grid_columnconfigure(0, weight=1)

        row = 0
        row = build_status_banner(self, self.main_frame, row)
        row = build_scan_and_protection(self, self.main_frame, row)
        row = build_scan_activity(self, self.main_frame, row)
        row = build_whitelist_and_quarantine(self, self.main_frame, row)
        row = build_updates_card(self, self.main_frame, row)

        customtkinter.CTkLabel(
            self.main_frame, text="", height=12,
        ).grid(row=row, column=0)

        # Populate live data on screen creation
        self.app.after(100, self._refresh_db_info)
        self.app.after(200, self._refresh_whitelist)
        self.app.after(300, self._refresh_quarantine)

        # If we already know the status from a previous poll, apply it
        # immediately so the card doesn't flash "Checking..." on every visit.
        # Then kick off the live poll after a short delay.
        if self._last_status is not None:
            self._apply_realtime_status_ui(self._last_status)
        self.app.after(500, self._update_realtime_status)

        return self.main_frame

    def destroy(self):
        self._stop_auto_update_scheduler()
        self._banner_frame = None
        self._banner_label = None
        self._banner_subtitle = None
        self._banner_action_btn = None
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.destroy()
            self.main_frame = None

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

        # State-driven card configuration matching the VPN status card style
        states = {
            "not_installed": {
                "bg": _COLOR_SETUP_BG,
                "title": "Not Installed",
                "title_color": _COLOR_SETUP_TEXT,
                "subtitle": (
                    "ClamAV binaries were not found. "
                    "Reinstall Resistine or run the build script "
                    "to set up antivirus protection."
                ),
                "action": None,
            },
            "no_database": {
                "bg": _COLOR_SETUP_BG,
                "title": "Setup Required",
                "title_color": _COLOR_SETUP_TEXT,
                "subtitle": (
                    "No signature database found. "
                    "Tap Update Now below to download the latest "
                    "malware definitions before scanning."
                ),
                "action": None,
            },
            "protected": {
                "bg": COLOR_OK_BG,
                "title": "Protected",
                "title_color": COLOR_OK_TEXT,
                "subtitle": (
                    "Real-time malware protection is active"
                    if status.get("clamonacc_running")
                    else "On-demand scanning is active"
                ),
                "action": None,
            },
            "approval_required": {
                "bg": COLOR_WARN_BG,
                "title": "Approval Required",
                "title_color": COLOR_WARN_TEXT,
                "subtitle": (
                    "On-demand scanning is available. "
                    "Enable ClamAV daemons in System Settings "
                    "\u203A General \u203A Login Items "
                    "for faster scans and real-time protection."
                ),
                "action": ("Open Login Items", clamav.open_login_items_settings),
            },
            "fda_required": {
                "bg": COLOR_WARN_BG,
                "title": "Full Disk Access Required",
                "title_color": COLOR_WARN_TEXT,
                "subtitle": (
                    "Resistine needs Full Disk Access to monitor files "
                    "in real time. Grant access in System Settings "
                    "\u203A Privacy & Security \u203A Full Disk Access."
                ),
                "action": ("Open Settings", clamav.open_fda_settings),
            },
            "error": {
                "bg": COLOR_ERR_BG,
                "title": "Protection Offline",
                "title_color": COLOR_ERR_TEXT,
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

        def _run():
            ok, msg = clamav.activate_system_daemons()
            self.app.after(0, self._handle_protection_started, ok, msg)

        threading.Thread(target=_run, daemon=True).start()

    def _handle_protection_started(self, ok: bool, msg: str):
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

        file_count = [0]  # mutable counter for closure

        def on_progress(line: str):
            self.app.after(0, self._log_append, line)
            # Update status label with current file being scanned
            if ":" in line and ("OK" in line or "FOUND" in line):
                file_count[0] += 1
                fpath = line.split(":")[0].strip()
                # Show path relative to scan target for context
                if os.path.isdir(target):
                    rel = os.path.relpath(fpath, os.path.dirname(target))
                else:
                    rel = os.path.basename(fpath)
                count_str = f" ({file_count[0]} scanned)"
                self.app.after(
                    0, self._scan_status_label.configure,
                    {"text": f"Scanning: {rel}{count_str}"},
                )

        def on_complete(result: ScanResult):
            self.app.after(0, self._handle_scan_complete, result)

        self._scan_handle = scan(
            target, on_progress=on_progress, on_complete=on_complete,
        )

    def _cancel_scan(self):
        """Cancel the running scan."""
        if self._scan_handle and not self._scan_handle.cancelled:
            self._scan_handle.cancel()
            self._log_append("Cancelling scan...")
            cancel_btn = self._action_buttons.get("cancel_scan")
            if cancel_btn:
                cancel_btn.configure(state="disabled")

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
            # Collect infected paths
            infected_paths = []
            for infection_line in result.infections:
                # Format: "/path/to/file: Virus.Name FOUND"
                parts = infection_line.rsplit(":", 1)
                if len(parts) == 2:
                    infected_paths.append(parts[0].strip())
            if infected_paths:
                self._offer_quarantine_batch(infected_paths)
        else:
            self._scan_status_label.configure(text="No threats found")

    def _offer_quarantine_batch(self, filepaths: list[str]):
        """Ask user whether to quarantine all infected files at once."""
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
            ok, msg = clamav.quarantine_file(filepath)
            basename = os.path.basename(filepath)
            if ok:
                self._log_append(f"Quarantined: {basename}")
                quarantined += 1
            else:
                self._log_append(f"Quarantine failed ({basename}): {msg}")
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
                font=font(12), text_color=COLOR_MUTED,
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
                font=font(12), text_color=COLOR_MUTED,
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
                row_frame, text="Delete", width=50, height=22,
                font=font(10), fg_color="transparent",
                hover_color=("#FEE2E2", "#3B1010"),
                text_color=("#DC2626", "#F87171"),
                command=lambda p=qpath: self._delete_quarantined(p),
            ).grid(row=0, column=1, sticky="e", padx=(4, 0))

    def _delete_quarantined(self, qpath: str):
        name = os.path.basename(qpath).replace(".quarantined", "")
        if messagebox.askyesno(
            "Delete Quarantined File",
            f"Permanently delete '{name}'?",
            parent=self.app,
        ):
            clamav.delete_quarantined(qpath)
            self._refresh_quarantine()
