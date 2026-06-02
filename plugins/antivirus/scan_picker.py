"""Unified scan-target picker dialog.

On macOS, uses the native NSOpenPanel which supports selecting files and
folders simultaneously. On Windows/Linux, presents a custom CTkToplevel
where users can add files, folders, or both before launching a scan.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""
from __future__ import annotations

import os
import platform
from tkinter import filedialog

import customtkinter

from plugins.antivirus.theme import CORNER_R, font


def pick_scan_targets(parent) -> list[str] | None:
    """Open a platform-appropriate picker and return selected paths.

    Returns a list of paths on success, or None if the user cancelled.
    """
    if platform.system() == "Darwin":
        return _pick_native_macos(parent)
    return _pick_custom_dialog(parent)


# ── macOS native picker via NSOpenPanel ──────────────────────────


def _pick_native_macos(parent) -> list[str] | None:
    """Use NSOpenPanel to select files and/or folders in one dialog."""
    try:
        from AppKit import NSModalResponseOK, NSOpenPanel
    except ImportError:
        # pyobjc not available — fall back to custom dialog
        return _pick_custom_dialog(parent)

    panel = NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(True)
    panel.setTitle_("Select Files or Folders to Scan")
    panel.setPrompt_("Scan")

    if panel.runModal() != NSModalResponseOK:
        return None

    urls = panel.URLs()
    paths = [str(url.path()) for url in urls]
    return paths if paths else None


# ── Custom dialog for Windows / Linux ────────────────────────────


def _pick_custom_dialog(parent) -> list[str] | None:
    """Show the CTkToplevel picker dialog and return results."""
    dialog = _ScanPickerDialog(parent)
    parent.wait_window(dialog)
    return dialog.result


class _ScanPickerDialog(customtkinter.CTkToplevel):
    """Modal dialog for selecting files and/or folders to scan."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Select Scan Targets")
        self.geometry("520x400")
        self.resizable(True, True)
        self.transient(parent)

        self.result: list[str] | None = None
        self._paths: list[str] = []

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        # grab_set after UI is built — avoids Wayland grab issues
        self.grab_set()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Top button row ──
        btn_row = customtkinter.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))

        customtkinter.CTkButton(
            btn_row, text="Add Files\u2026", width=120, height=32,
            corner_radius=8, font=font(12),
            command=self._add_files,
        ).pack(side="left", padx=(0, 8))

        customtkinter.CTkButton(
            btn_row, text="Add Folders\u2026", width=120, height=32,
            corner_radius=8, font=font(12),
            command=self._add_folders,
        ).pack(side="left", padx=(0, 8))

        self._remove_btn = customtkinter.CTkButton(
            btn_row, text="Remove Last", width=100, height=32,
            corner_radius=8, font=font(12),
            fg_color="transparent", border_width=1,
            command=self._remove_last,
        )
        self._remove_btn.pack(side="left")

        # ── Scrollable list of targets ──
        self._listbox = customtkinter.CTkTextbox(
            self, corner_radius=CORNER_R, height=200,
            font=font(11), state="disabled",
        )
        self._listbox.grid(
            row=1, column=0, sticky="nsew", padx=16, pady=(0, 6),
        )

        # ── Bottom action row ──
        bottom = customtkinter.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))

        self._count_label = customtkinter.CTkLabel(
            bottom, text="0 items selected", font=font(11),
        )
        self._count_label.pack(side="left")

        customtkinter.CTkButton(
            bottom, text="Cancel", width=80, height=32,
            corner_radius=8, font=font(12),
            fg_color="transparent", border_width=1,
            command=self._on_cancel,
        ).pack(side="right", padx=(8, 0))

        self._scan_btn = customtkinter.CTkButton(
            bottom, text="Scan", width=80, height=32,
            corner_radius=8, font=font(12),
            command=self._on_scan,
        )
        self._scan_btn.pack(side="right")
        self._scan_btn.configure(state="disabled")

    # ── Actions ──

    def _add_files(self):
        paths = list(filedialog.askopenfilenames(
            title="Select Files to Scan", parent=self,
        ) or [])
        for p in paths:
            if p not in self._paths:
                self._paths.append(p)
        if paths:
            self._refresh_list()

    def _add_folders(self):
        path = filedialog.askdirectory(
            title="Select Folder to Scan", parent=self,
        )
        if path and path not in self._paths:
            self._paths.append(path)
            self._refresh_list()

    def _remove_last(self):
        if not self._paths:
            return
        self._paths.pop()
        self._refresh_list()

    def _refresh_list(self):
        self._listbox.configure(state="normal")
        self._listbox.delete("1.0", "end")
        for p in self._paths:
            prefix = "[DIR]" if os.path.isdir(p) else "[FILE]"
            self._listbox.insert("end", f"{prefix}  {p}\n")
        self._listbox.configure(state="disabled")

        count = len(self._paths)
        self._count_label.configure(
            text=f"{count} item{'s' if count != 1 else ''} selected",
        )
        self._scan_btn.configure(
            state="normal" if count > 0 else "disabled",
        )

    def _on_scan(self):
        self.result = list(self._paths)
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.grab_release()
        self.destroy()
