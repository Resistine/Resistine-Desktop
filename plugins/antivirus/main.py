"""Antivirus plugin for Resistine Desktop.

Provides file/directory scanning, real-time protection, signature updates,
quarantine management, and whitelist via ClamAV binaries.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import threading
from tkinter import filedialog, messagebox

import customtkinter

from plugins.antivirus import clamav
from plugins.antivirus.scanner import ScanResult, scan
from plugins.antivirus.theme import (
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
            supported_systems=["Darwin"],
            translations={"US": "Antivirus", "ES": "Antivirus", "FR": "Antivirus"},
            icon_light_path=os.path.join(_PLUGIN_DIR, "antivirus_light.png"),
            icon_dark_path=os.path.join(_PLUGIN_DIR, "antivirus_dark.png"),
            uninstall_enabled=True,
        )
        self.app = app
        self._auto_update_on = True
        self._action_buttons = {}
        self._banner_frame = None
        self._banner_label = None
        self._scanning = False
        self._scan_handle = None
        self._last_state = None
        self.status = self.get_status()

        # Register system-level ClamAV daemons via SMAppService (non-blocking)
        import platform
        if platform.system() == "Darwin":
            threading.Thread(
                target=clamav.ensure_daemons_registered, daemon=True,
            ).start()

    def check_status(self):
        if self._last_state == "protected":
            return "OK"
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
        self.app.after(500, self._update_realtime_status)

        return self.main_frame

    def destroy(self):
        self._banner_frame = None
        self._banner_label = None
        if hasattr(self, "main_frame") and self.main_frame:
            self.main_frame.destroy()
            self.main_frame = None

    # ── UI Event Handlers ────────────────────────────────────

    def _update_realtime_status(self):
        """Poll daemon state and update the banner."""
        def _check():
            status = clamav.get_realtime_status()
            try:
                self.app.after(0, self._apply_realtime_status, status)
            except Exception:
                pass  # App destroyed during check

        threading.Thread(target=_check, daemon=True).start()

    def _apply_realtime_status(self, status: dict):
        from plugins.antivirus.theme import (
            COLOR_ERR_BG,
            COLOR_ERR_TEXT,
        )

        state = status["state"]
        self._last_state = state
        self.status = self.check_status()

        if self._banner_frame is None:
            self._schedule_status_poll()
            return

        if state == "protected":
            self._banner_frame.configure(fg_color=COLOR_OK_BG)
            self._banner_label.configure(
                text="\u2713  Protected", text_color=COLOR_OK_TEXT,
            )
        elif state == "warning":
            self._banner_frame.configure(fg_color=COLOR_WARN_BG)
            self._banner_label.configure(
                text="\u26A0  Approve in System Settings \u203A Login Items",
                text_color=COLOR_WARN_TEXT,
            )
        else:  # error
            self._banner_frame.configure(fg_color=COLOR_ERR_BG)
            self._banner_label.configure(
                text="\u2717  Protection Offline — daemons not running",
                text_color=COLOR_ERR_TEXT,
            )

        self._schedule_status_poll()

    def _schedule_status_poll(self):
        """Schedule the next realtime status poll if the UI is still alive."""
        try:
            if hasattr(self, "main_frame") and self.main_frame.winfo_exists():
                self.app.after(10000, self._update_realtime_status)
        except Exception:
            pass

    def _toggle_auto_update(self):
        self._auto_update_on = self._auto_update_switch.get()
        logger.info(
            f"Antivirus: auto-update toggled "
            f"{'on' if self._auto_update_on else 'off'}",
        )

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
        for key in ("scan_file", "scan_directory", "analysis"):
            btn = self._action_buttons.get(key)
            if btn:
                btn.configure(state=state)

    # ── Action Router ─────────────────────────────────────────

    def _on_action(self, action_key: str):
        logger.info(f"Antivirus: action triggered — {action_key}")

        actions = {
            "scan_file": self._start_file_scan,
            "scan_directory": self._start_directory_scan,
            "analysis": self._start_analysis,
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
        self._run_scan(path)

    def _start_directory_scan(self):
        if self._scanning:
            return
        path = filedialog.askdirectory(
            title="Select Directory to Scan", parent=self.app,
        )
        if not path:
            return
        self._run_scan(path)

    def _start_analysis(self):
        """Quick scan of common threat locations."""
        if self._scanning:
            return
        home = os.path.expanduser("~")
        target = os.path.join(home, "Downloads")
        if not os.path.isdir(target):
            target = home
        self._run_scan(target)

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

        def on_progress(line: str):
            self.app.after(0, self._log_append, line)

        def on_complete(result: ScanResult):
            self.app.after(0, self._handle_scan_complete, result)

        self._scan_handle = scan(
            target, on_progress=on_progress, on_complete=on_complete,
        )

    def _cancel_scan(self):
        """Cancel the running scan."""
        if self._scan_handle:
            self._scan_handle.cancel()
            self._log_append("Cancelling scan...")

    def _handle_scan_complete(self, result: ScanResult):
        self._scanning = False
        self._scan_handle = None
        self._scan_progress.stop()
        self._scan_progress.set(1.0 if not result.error else 0)
        self._scan_progress.configure(mode="determinate")
        self._scan_progress.grid_remove()
        self._set_scan_buttons_state("normal")

        # Hide cancel button
        cancel_btn = self._action_buttons.get("cancel_scan")
        if cancel_btn:
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
        choice = messagebox.askyesnocancel(
            "Add to Whitelist",
            "Whitelist a directory?\n\n"
            "Yes = directory, No = file, Cancel = abort",
            parent=self.app,
        )
        if choice is None:
            return
        if choice:
            path = filedialog.askdirectory(
                title="Select Directory to Whitelist", parent=self.app,
            )
        else:
            path = filedialog.askopenfilename(
                title="Select File to Whitelist", parent=self.app,
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
