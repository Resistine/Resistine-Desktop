"""
Wazuh SIEM Agent Plugin
Install and manage the Wazuh agent from the Resistine Desktop sidebar.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import os
import platform
import threading

import customtkinter
from customtkinter import ThemeManager

from plugins.base_plugin import BasePlugin
from plugins.wazuh.config import WAZUH_MANAGER
from utils.logger import logger

# --- Platform Detection ---
_PLATFORM = platform.system()
IS_MACOS = _PLATFORM == "Darwin"
IS_WINDOWS = _PLATFORM == "Windows"
IS_LINUX = _PLATFORM == "Linux"

# --- Platform-conditional imports ---
_platform_supported = False
if IS_MACOS:
    from plugins.wazuh.agent.wazuh_functions_darwin import (
        full_install,
        get_agent_group,
        get_agent_name,
        get_agent_status,
        is_agent_installed,
        start_agent,
        stop_agent,
    )
    _platform_supported = True


class Plugin(BasePlugin):
    """Plugin class for the Wazuh SIEM agent."""

    def __init__(self, app):
        super().__init__(
            id="011",
            version="2026.01.04-alpha",
            order=5,
            name="Wazuh",
            status=None,
            description="Install and manage the Wazuh SIEM agent.",
            supported_systems=["Darwin"],
            translations={"US": "Wazuh", "ES": "Wazuh", "FR": "Wazuh"},
            icon_light_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "wazuh_light.png"
            ),
            icon_dark_path=os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "wazuh_dark.png"
            ),
            uninstall_enabled=True,
        )
        self.app = app
        self._status_poll_id = None
        self._installing = False
        self.status = self.get_status()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def check_status(self):
        if not _platform_supported:
            return None
        try:
            state = get_agent_status()
        except Exception:
            return "Warning"
        if state == "Running":
            return "OK"
        if state == "Stopped":
            return "Error"
        return "Warning"  # Not Installed

    # ------------------------------------------------------------------
    # Main Screen
    # ------------------------------------------------------------------

    def create_main_screen(self):
        self._stop_status_polling()

        if not _platform_supported:
            return self._unsupported_screen()

        installed = is_agent_installed()
        logger.info(f"Wazuh create_main_screen: is_agent_installed={installed}")
        if installed:
            return self._status_screen()
        return self._install_screen()

    # ------------------------------------------------------------------
    # Unsupported Platform Screen
    # ------------------------------------------------------------------

    def _unsupported_screen(self):
        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        customtkinter.CTkLabel(
            self.main_container,
            text="Unsupported Platform",
            font=customtkinter.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(40, 5))

        customtkinter.CTkLabel(
            self.main_container,
            text=f"Wazuh agent management is not yet available on {_PLATFORM}.",
            font=customtkinter.CTkFont(size=14),
            text_color=("#666666", "#aaaaaa"),
        ).grid(row=1, column=0, padx=20, pady=5)

        return self.main_container

    # ------------------------------------------------------------------
    # Install Screen
    # ------------------------------------------------------------------

    def _install_screen(self):
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 15)

        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        scroll = customtkinter.CTkScrollableFrame(
            self.main_container, corner_radius=0, fg_color="transparent"
        )
        scroll.grid(row=0, column=0, sticky="nsew", padx=20, pady=10)
        scroll.grid_columnconfigure(0, weight=1)

        # Title
        customtkinter.CTkLabel(
            scroll,
            text="Wazuh SIEM Agent",
            font=customtkinter.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(10, 5))

        customtkinter.CTkLabel(
            scroll,
            text=(
                "The Wazuh agent collects security telemetry from this machine "
                "and reports to the Resistine SIEM dashboard."
            ),
            font=customtkinter.CTkFont(size=13),
            text_color=("#666666", "#aaaaaa"),
            wraplength=500,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 15))

        # Agent info card
        info_frame = customtkinter.CTkFrame(
            scroll,
            corner_radius=corner_radius,
            fg_color=("#ffffff", "#141414"),
            border_width=1,
            border_color=("#dddddd", "#333333"),
        )
        info_frame.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        info_frame.grid_columnconfigure(1, weight=1)

        info_items = {
            "Agent Name": get_agent_name(),
            "Agent Group": get_agent_group(),
            "Manager": WAZUH_MANAGER,
        }
        for idx, (label, value) in enumerate(info_items.items()):
            customtkinter.CTkLabel(
                info_frame,
                text=f"{label}:",
                text_color=("#666666", "#aaaaaa"),
                font=customtkinter.CTkFont(size=13),
            ).grid(row=idx, column=0, padx=15, pady=5, sticky="w")
            customtkinter.CTkLabel(
                info_frame,
                text=value,
                font=customtkinter.CTkFont(size=13, weight="bold"),
            ).grid(row=idx, column=1, padx=15, pady=5, sticky="e")

        # Progress label (hidden by default)
        self._progress_label = customtkinter.CTkLabel(
            scroll,
            text="",
            font=customtkinter.CTkFont(size=13),
            text_color=("#3a7ebf", "#5b9bd5"),
        )
        self._progress_label.grid(row=3, column=0, sticky="w", pady=(0, 5))

        # Install button
        self._install_btn = customtkinter.CTkButton(
            scroll,
            text="Install Agent",
            height=40,
            corner_radius=8,
            font=customtkinter.CTkFont(size=14, weight="bold"),
            command=self._start_installation,
        )
        self._install_btn.grid(row=4, column=0, sticky="ew", pady=(0, 20))

        return self.main_container

    # ------------------------------------------------------------------
    # Status / Control Screen
    # ------------------------------------------------------------------

    def _status_screen(self):
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 15)

        self.main_container = customtkinter.CTkFrame(
            self.app, corner_radius=0, fg_color="transparent"
        )
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        scroll = customtkinter.CTkScrollableFrame(
            self.main_container, corner_radius=0, fg_color="transparent"
        )
        scroll.grid(row=0, column=0, sticky="nsew", padx=20, pady=10)
        scroll.grid_columnconfigure(0, weight=1)

        state = get_agent_status()
        is_running = state == "Running"

        # Status bar
        status_text = "Running" if is_running else "Stopped"
        status_color = ("#1E8E3E", "#2CC985") if is_running else ("#C5221F", "#FF474C")

        status_frame = customtkinter.CTkFrame(
            scroll,
            corner_radius=corner_radius,
            fg_color=("#ffffff", "#141414"),
            border_width=1,
            border_color=("#dddddd", "#333333"),
        )
        status_frame.grid(row=0, column=0, sticky="ew", pady=(10, 5))
        status_frame.grid_columnconfigure(0, weight=1)

        customtkinter.CTkLabel(
            status_frame,
            text=f"Wazuh Agent: {status_text}",
            text_color=status_color,
            font=customtkinter.CTkFont(family="Inter", size=20, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=10, sticky="w")

        # Start / Stop toggle
        self._agent_toggle = customtkinter.CTkSwitch(
            status_frame,
            text="Agent Service",
            command=lambda: self._toggle_agent(self._agent_toggle.get()),
            switch_width=50,
            switch_height=25,
            onvalue=1,
            offvalue=0,
        )
        if is_running:
            self._agent_toggle.select()
        else:
            self._agent_toggle.deselect()
        self._agent_toggle.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

        # Info banner
        banner_bg = (
            ("#E6F4EA", "#1E3A2F") if is_running else ("#FDEDEC", "#3E2B2C")
        )
        banner_fg = (
            ("#1E8E3E", "#2CC985") if is_running else ("#C5221F", "#FF474C")
        )
        banner_text = (
            "Agent is reporting to the SIEM dashboard"
            if is_running
            else "Agent is not running"
        )

        banner = customtkinter.CTkFrame(
            scroll, corner_radius=corner_radius, fg_color=banner_bg
        )
        banner.grid(row=1, column=0, sticky="ew", pady=5)

        customtkinter.CTkLabel(
            banner,
            text=banner_text,
            text_color=banner_fg,
            font=customtkinter.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=10, sticky="w")

        # Agent info card
        customtkinter.CTkLabel(
            scroll,
            text="AGENT DETAILS",
            font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"),
            text_color="#3a7ebf",
        ).grid(row=2, column=0, sticky="w", pady=(15, 5))

        info_frame = customtkinter.CTkFrame(
            scroll,
            corner_radius=corner_radius,
            fg_color=("#ffffff", "#141414"),
            border_width=1,
            border_color=("#dddddd", "#333333"),
        )
        info_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)

        details = {
            "Status": state,
            "Agent Name": get_agent_name(),
            "Agent Group": get_agent_group(),
            "Manager": WAZUH_MANAGER,
            "Platform": f"{_PLATFORM} {platform.release()}",
        }
        for idx, (key, value) in enumerate(details.items()):
            customtkinter.CTkLabel(
                info_frame,
                text=f"{key}:",
                text_color=("#666666", "#aaaaaa"),
            ).grid(row=idx, column=0, padx=15, pady=5, sticky="w")
            customtkinter.CTkLabel(
                info_frame,
                text=value,
                font=customtkinter.CTkFont(family="Inter", size=13, weight="bold"),
            ).grid(row=idx, column=1, padx=15, pady=5, sticky="e")

        # Start polling
        self._start_status_polling()

        return self.main_container

    # ------------------------------------------------------------------
    # Installation logic (background thread)
    # ------------------------------------------------------------------

    def _start_installation(self):
        if self._installing:
            return
        self._installing = True
        self._install_btn.configure(state="disabled", text="Installing...")

        def _progress(msg):
            self.app.after(0, lambda: self._progress_label.configure(text=msg))

        def _done(success):
            logger.info(f"Wazuh _done: success={success}")
            self._installing = False
            if success:
                logger.info(f"Wazuh _done: is_agent_installed={is_agent_installed()}")
                self.app.show_notification(
                    "Wazuh agent installed successfully!", type="success"
                )
                self._update_plugin()
            else:
                self._install_btn.configure(state="normal", text="Retry Install")
                self.app.show_notification(
                    "Wazuh agent installation failed", type="error"
                )

        def _run():
            try:
                ok = full_install(progress_callback=_progress)
            except Exception as e:
                logger.error(f"Installation error: {e}")
                ok = False
                _progress(f"Error: {e}")

            # Schedule on main thread — capture result by value via default arg
            self.app.after(100, lambda s=ok: _done(s))

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Start / Stop toggle
    # ------------------------------------------------------------------

    def _toggle_agent(self, switch_value):
        state = get_agent_status()
        is_running = state == "Running"

        if switch_value == 1 and not is_running:
            success = start_agent()
            if success:
                self.app.show_notification("Wazuh agent started", type="info")
            else:
                self.app.show_notification("Failed to start agent", type="error")
            self._update_plugin()

        elif switch_value == 0 and is_running:
            success = stop_agent()
            if success:
                self.app.show_notification("Wazuh agent stopped", type="info")
            else:
                self.app.show_notification("Failed to stop agent", type="error")
            self._update_plugin()

    # ------------------------------------------------------------------
    # Status polling (every 10 seconds)
    # ------------------------------------------------------------------

    def _start_status_polling(self):
        if not _platform_supported:
            return
        self._stop_status_polling()

        def poll():
            if not hasattr(self, "main_container") or not self.main_container.winfo_exists():
                self._status_poll_id = None
                return

            new_status = self.check_status()
            if new_status != self.status:
                logger.info(f"Wazuh status changed: {self.status} -> {new_status}")
                self.status = new_status
                self._update_plugin()
                return

            self._status_poll_id = self.app.after(10000, poll)

        self._status_poll_id = self.app.after(10000, poll)

    def _stop_status_polling(self):
        if self._status_poll_id:
            self.app.after_cancel(self._status_poll_id)
            self._status_poll_id = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_plugin(self):
        """Rebuild the plugin screen if it is currently displayed."""
        for p in self.app.plugin_list:
            if p.id == self.id:
                current = getattr(self.app, "current_frame_name", "")
                target = f"frame_{p.get_name()}"
                logger.info(f"Wazuh _update_plugin: current={current!r} target={target!r} match={current == target}")
                if current == target:
                    if hasattr(self, "main_container"):
                        try:
                            self.main_container.destroy()
                        except Exception:
                            pass
                    p.create_main_screen().grid(row=0, column=1, sticky="nsew")
                return

    def destroy(self):
        self._stop_status_polling()
