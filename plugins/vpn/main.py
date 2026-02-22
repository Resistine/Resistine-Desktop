## @file plugins/vpn/main.py
## @package vpn_plugin
## @namespace vpn_plugin
## @class vpn_plugin::Plugin
"""
This module contains the main plugin class for the VPN plugin.
The VPN plugin displays VPN information and allows the user to manage VPN tunnels.
Author: Javier Perez and Jacqueline Edoro 
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from plugins.base_plugin import BasePlugin
from utils.logger import logger
import customtkinter
import os
from tkinter import filedialog
import platform
import subprocess
# --- Platform Detection (single source of truth) ---
_PLATFORM = platform.system()
IS_MACOS = _PLATFORM == "Darwin"
IS_WINDOWS = _PLATFORM == "Windows"
IS_LINUX = _PLATFORM == "Linux"

# --- Platform Specific Imports ---
if IS_WINDOWS:
    from plugins.vpn.wireguard.vpn_functions_windows import (
        get_writable_wireguard_dir,
        check_wireguard_installed,
        check_service_status,
        start_vpn,
        stop_vpn,
    )
    from plugins.vpn.wireguard.vpn_windows_client import (
        get_status, connect, disconnect, toggle
    )
    wireguard_folder = get_writable_wireguard_dir()

elif IS_LINUX:
    from plugins.vpn.wireguard.vpn_functions_linux import *
    wireguard_folder = get_writable_wireguard_dir()

elif IS_MACOS:
    from plugins.vpn.wireguard.vpn_functions_darwin import *
    wireguard_folder = get_writable_wireguard_dir()

# DNS Configuration - Change this value to update DNS across the application
DNS_SERVER = "10.49.11.10"

# Global cache for interface mapping (e.g., config 'wg0' -> system 'utun3')
_interface_cache = {}
active_client_name = None
my_vpn_status = "Stopped"

# --- Config Manager (module-level for use in init) ---
from plugins.vpn.config_manager import VPNConfigManager
_config_manager = VPNConfigManager(wireguard_folder)
_config_manager.migrate_legacy_config()

# --- Initialization Logic ---
def initialize_vpn_status():
    global active_client_name, my_vpn_status, existing_interfaces

    existing_interfaces = []

    # First, check if WireGuard is actually installed
    if not check_wireguard_installed():
        logger.warning("⚠️ WireGuard not installed - VPN features disabled")
        my_vpn_status = "Stopped"
        return

    if IS_MACOS:
        # macOS uses Network Extension — wg show interfaces won't see the tunnel.
        # First verify the extension is actually enabled in Login Items & Extensions.
        # A stale NETunnelProviderManager can make the CLI report a false status.
        if not is_extension_enabled():
            logger.warning("Network extension is not enabled — VPN unavailable")
            my_vpn_status = "Stopped"
        else:
            # Extension is enabled, query actual connection status via CLI
            status = check_service_status("vpn", DNS_SERVER)
            if status == "Running":
                # Use config manager to determine the active config name
                active_name = _config_manager.get_active_config_name()
                if active_name:
                    active_client_name = active_name
                my_vpn_status = "Running"
            else:
                my_vpn_status = "Stopped"
    
    elif IS_WINDOWS:
        try:
            active_name = _config_manager.get_active_config_name()
            if active_name:
                state = check_service_status(active_name)
                if state == "Running":
                    active_client_name = active_name
                    my_vpn_status = "Running"
                else:
                    my_vpn_status = "Stopped"
            else:
                my_vpn_status = "Stopped"
        except Exception as e:
            logger.warning(f"⚠️ Could not determine VPN status on Windows: {e}")
            my_vpn_status = "Stopped"
    elif IS_LINUX:
        try:
            existing_interfaces = os.popen('wg show interfaces').read().split()
        except Exception as e:
            logger.warning(f"⚠️ Could not enumerate WireGuard interfaces: {e}")
            existing_interfaces = []

#? On Linux, we can check the status of each interface to find the active one. On Windows/macOS, we rely on service/extension status and config manager.
    if not IS_MACOS:
        # Check if any known interface is running (Linux/Windows only)
        for interface in existing_interfaces:
            if interface.strip():
                status = check_service_status(interface, DNS_SERVER)
                if status == "Running":
                    active_client_name = interface
                    break

        my_vpn_status = check_service_status(active_client_name, DNS_SERVER) if active_client_name else "Stopped"

    logger.info(f"VPN Status in Init: {my_vpn_status}")

# --- Helper Functions ---


def update_listbox_colors(listbox):
    if customtkinter.get_appearance_mode() == "Dark":
        listbox.config(fg="white", bg="#2e2e2e")
    else:
        listbox.config(fg="black", bg="lightgray")

# --- Run Init ---
initialize_vpn_status()


# --- Main Plugin Class ---

class Plugin(BasePlugin):
    """
    @brief Plugin class for the VPN plugin.
    """
    def __init__(self, app):
        super().__init__(
            id="008",
            version="2025.01.01",
            order=3,
            name="VPN",
            status=None, # Default status
            description="VPN Management",
            supported_systems=["Windows", "Darwin", "Linux"],
            translations={"US": "VPN", "ES": "VPN", "FR": "VPN"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "vpn_light.png"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "vpn_dark.png"),
        )
        self.app = app
        self.config_dir = wireguard_folder
        self.config_manager = _config_manager
        self.active_interface = None
        self._extension_poll_id = None
        self._last_extension_state = None
        # Set status dynamically after super().__init__
        self.status = self.get_status()

    def check_status(self):
        """Dynamic check of the VPN status."""
        if IS_MACOS and not is_extension_enabled():
            return "Error"
        if my_vpn_status == "Running":
            return "OK"
        elif my_vpn_status == "Connecting":
            return "Info"
        return "Warning"

    @staticmethod
    def validate_wireguard_config(content):
        """Validate that content is a well-formed WireGuard config.

        Checks for required [Interface] and [Peer] sections and their
        mandatory keys.  Returns (True, "") on success or (False, reason)
        on failure.
        """
        MAX_CONFIG_SIZE = 10_240  # 10 KB — more than enough for any config
        if len(content) > MAX_CONFIG_SIZE:
            return False, "File is too large to be a valid WireGuard config"

        lines = content.splitlines()
        sections = {}
        current_section = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                current_section = stripped[1:-1]
                sections.setdefault(current_section, set())
            elif "=" in stripped and current_section:
                key = stripped.split("=", 1)[0].strip()
                sections[current_section].add(key.lower())

        if "Interface" not in sections:
            return False, "Missing [Interface] section"
        if "Peer" not in sections:
            return False, "Missing [Peer] section"

        iface_keys = sections["Interface"]
        peer_keys = sections["Peer"]

        if "privatekey" not in iface_keys:
            return False, "Missing PrivateKey in [Interface]"
        if "address" not in iface_keys:
            return False, "Missing Address in [Interface]"
        if "publickey" not in peer_keys:
            return False, "Missing PublicKey in [Peer]"
        if "endpoint" not in peer_keys:
            return False, "Missing Endpoint in [Peer]"

        return True, ""

    def import_config(self):
        """Allows the user to import a WireGuard config file alongside existing configs."""
        global my_vpn_status, active_client_name

        file_path = filedialog.askopenfilename(
            title="Select WireGuard Config",
            filetypes=[("WireGuard Config", "*.conf"), ("All Files", "*.*")]
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as src:
                content = src.read()

            valid, reason = self.validate_wireguard_config(content)
            if not valid:
                logger.warning(f"Invalid config rejected: {reason}")
                self.app.show_notification(f"Invalid config: {reason}", type="error")
                return

            # Stop VPN if running before switching to imported config
            if my_vpn_status == "Running" and active_client_name:
                old_config_path = os.path.join(wireguard_folder, f"{active_client_name}.conf")
                stop_vpn(old_config_path)
                my_vpn_status = "Stopped"
                active_client_name = None

            # Import via config manager (keeps existing configs)
            success, config_name = self.config_manager.import_config(file_path, content)
            if not success:
                self.app.show_notification(f"Failed to import: {config_name}", type="error")
                return

            # Set imported config as active
            self.config_manager.set_active_config(config_name)

            logger.info(f"Imported config: {config_name}")
            self.app.show_notification("Configuration imported successfully!", type="success")
            self.update_plugin(self.id)

        except Exception as e:
            logger.error(f"Failed to import config: {e}")
            self.app.show_notification(f"Failed to import config: {e}", type="error")

    def get_selected_conf_file_name(self):
        """Get the active VPN config name from the config manager."""
        global active_client_name

        # If VPN is running, return the running interface name
        if active_client_name and my_vpn_status == "Running":
            return active_client_name

        # Use config manager to get the active config
        return self.config_manager.get_active_config_name()

    def get_system_info(self, tunnel_name):
        """Generates the system information dictionary for display."""
        global my_vpn_status
        data = self.get_configuration_values(tunnel_name) if tunnel_name else {}
        
        is_running = my_vpn_status == "Running"
        protocol = "WireGuard" if is_running else "Disconnected"
        
        # Parse Endpoint for display
        endpoint = data.get('endpoint', 'Unknown')
        if endpoint != 'Unknown' and ':' in endpoint:
            endpoint = endpoint.split(':')[0] # Just show IP/Host

        return {
            "Status": "Secured" if is_running else "Unsecured",
            "Protocol": protocol,
            "Tunnel Name": tunnel_name if tunnel_name else "None",
            "Server IP": endpoint,
            "Public Key": (data.get('public_key', 'N/A') or 'N/A')[:15] + '...' if data.get('public_key') else 'N/A',
            "Client IP": data.get('client_ip_address', 'N/A'),
            "System": f"{_PLATFORM} {platform.release()}"
        }

    def create_main_screen(self):
        """Create the main screen for the VPN plugin."""
        self._stop_extension_polling()
        return self.display_toggle_screen()

    def refresh_vpn_state(self):
        """Refresh VPN state from the Windows service."""
        global my_vpn_status, active_client_name

        if not IS_WINDOWS:
            return

        tunnel = self.get_selected_conf_file_name()
        if not tunnel:
            my_vpn_status = "Stopped"
            active_client_name = None
            return

        try:
            status = get_status(tunnel)
            my_vpn_status = status.get("state", "Stopped")
            active_client_name = tunnel if my_vpn_status == "Running" else None
        except Exception as e:
            logger.error(f"Status refresh failed: {e}")
            my_vpn_status = "Stopped"
            active_client_name = None

    def toggle_vpn_connection(self, switch_value):
        """Handles the toggle switch.
        
        Args:
            switch_value: 1 for ON, 0 for OFF
        """
        selected_conf_file = self.get_selected_conf_file_name()

        if not selected_conf_file:
            logger.error("❌ Cannot toggle: No VPN config found in wireguard directory.")
            self.app.show_notification("No VPN configuration found. Please log in or add a config.", type="error")
            # Reset switch to off if no config available
            if hasattr(self, 'vpn_toggle_switch'):
                self.vpn_toggle_switch.deselect()
            return

        # WINDOWS: use IPC service for connect/disconnect
        if IS_WINDOWS:
            # Always get fresh state from service before acting
            current = get_status(selected_conf_file)
            print(f"Current VPN status for '{selected_conf_file}': {current.get('state', 'Unknown')}")
            is_running = current.get("state") == "Running"

            if switch_value == 1 and not is_running:
                result = connect(selected_conf_file)
                if result.get("status") != "ok" and result.get("state") not in ("Starting", "Running"):
                    logger.error(f"Connect failed: {result.get('message', '')}")
                    self.app.show_notification("Failed to connect VPN", type="error")
            elif switch_value == 0 and is_running:
                result = disconnect(selected_conf_file)
                if result.get("status") != "ok":
                    logger.error(f"Disconnect failed: {result.get('message', '')}")
                    self.app.show_notification("Failed to disconnect VPN", type="error")

            self.refresh_vpn_state()
            self.update_plugin(self.id)

        else:
            # Logic: 1 = ON Request, 0 = OFF Request
            if switch_value == 1 and not is_running:
                # User wants to turn VPN ON and it's currently OFF
                logger.info(f"🔄 Toggle ON: Starting VPN tunnel: {selected_conf_file}")
                self.activate_tunnel(selected_conf_file)

            elif switch_value == 0 and is_running:
                # User wants to turn VPN OFF and it's currently ON
                logger.info(f"🔄 Toggle OFF: Stopping VPN tunnel: {selected_conf_file}")
                self.activate_tunnel(selected_conf_file)

            else:
                # Edge case: Switch state doesn't match VPN state
                logger.warning(f"⚠️ Switch state ({switch_value}) doesn't match VPN state (Running: {is_running}). Refreshing UI...")
                self.update_plugin(self.id)

    def display_toggle_screen(self):
        """Display the modern main screen with toggle and info."""
        
        selected_conf_file = self.get_selected_conf_file_name()
        
        self.main_container = customtkinter.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1) 
        
        scroll_frame = customtkinter.CTkScrollableFrame(self.main_container, corner_radius=0, fg_color="transparent")
        scroll_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=10)
        scroll_frame.grid_columnconfigure(0, weight=1)
        
        global my_vpn_status

        # On Windows, always refresh state from the service
        if IS_WINDOWS:
            self.refresh_vpn_state()

        # On macOS, detect if the extension was disabled after onboarding
        extension_disabled = IS_MACOS and not is_extension_enabled()
        if extension_disabled and my_vpn_status == "Running":
            # Extension was disabled while we thought VPN was on — correct the state
            my_vpn_status = "Stopped"
            active_client_name = None

        is_connected = my_vpn_status == "Running"

        if extension_disabled:
            status_text = "Extension Disabled"
            status_color = ("#C5221F", "#FF474C")
            warning_text = (
                "VPN extension is disabled. Enable it in System Settings > "
                "General > Login Items & Extensions > Network Extensions"
            )
            warning_bg = ("#FDEDEC", "#3E2B2C")
            warning_fg = ("#C5221F", "#FF474C")
            is_enabled = False
        elif not selected_conf_file:
            status_text = "No Configuration"
            status_color = ("#666666", "#aaaaaa")
            warning_text = "Please log in or add a VPN configuration"
            warning_bg = ("#F5F5F5", "#2A2A2A")
            warning_fg = ("#666666", "#aaaaaa")
            is_enabled = False
        else:
            status_text = "Connected" if is_connected else "Disconnected"
            status_color = ("#1E8E3E", "#2CC985") if is_connected else ("#C5221F", "#FF474C")
            warning_text = "Your connection is secure" if is_connected else "Your connection is not secure"
            warning_bg = ("#E6F4EA", "#1E3A2F") if is_connected else ("#FDEDEC", "#3E2B2C")
            warning_fg = ("#1E8E3E", "#2CC985") if is_connected else ("#C5221F", "#FF474C")
            is_enabled = True

        # Get theme corner radius
        from customtkinter import ThemeManager
        corner_radius = ThemeManager.theme.get("Theme", {}).get("corner_radius", 15)
        
        # --- 1. Connection Status Bar ---
        status_frame = customtkinter.CTkFrame(scroll_frame, corner_radius=corner_radius, fg_color=("#ffffff", "#141414"), border_width=1, border_color=("#dddddd", "#333333"))
        status_frame.grid(row=0, column=0, sticky="ew", pady=(10, 5))
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)

        disconnected_label = customtkinter.CTkLabel(status_frame, text=status_text, text_color=status_color, font=customtkinter.CTkFont(family="Inter", size=20, weight="bold"))
        disconnected_label.grid(row=0, column=0, padx=20, pady=10, sticky="w")
        
        toggle_initial_value = 1 if is_connected else 0
        self.vpn_toggle_switch = customtkinter.CTkSwitch(
            status_frame, 
            text="VPN Connection", 
            command=lambda: self.toggle_vpn_connection(self.vpn_toggle_switch.get()),
            switch_width=50, 
            switch_height=25, 
            onvalue=1, 
            offvalue=0,
            state="normal" if is_enabled else "disabled"
        )
        if toggle_initial_value == 1 and is_enabled:
            self.vpn_toggle_switch.select() 
        else:
            self.vpn_toggle_switch.deselect()
            
        self.vpn_toggle_switch.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

        # --- 2. Config Selector Dropdown ---
        configs = self.config_manager.list_configs()
        if len(configs) > 1:
            selector_frame = customtkinter.CTkFrame(scroll_frame, corner_radius=corner_radius, fg_color=("#ffffff", "#141414"), border_width=1, border_color=("#dddddd", "#333333"))
            selector_frame.grid(row=1, column=0, sticky="ew", pady=5)
            selector_frame.grid_columnconfigure(1, weight=1)

            customtkinter.CTkLabel(
                selector_frame, text="Configuration:",
                font=customtkinter.CTkFont(family="Inter", size=13),
                text_color=("#666666", "#aaaaaa")
            ).grid(row=0, column=0, padx=(15, 5), pady=10, sticky="w")

            config_display_names = [c["display_name"] for c in configs]
            active_display = self.config_manager.get_display_name(selected_conf_file) if selected_conf_file else (config_display_names[0] if config_display_names else "None")

            self.config_selector = customtkinter.CTkOptionMenu(
                selector_frame,
                values=config_display_names,
                command=self._on_config_selected,
                height=36,
                corner_radius=8,
            )
            self.config_selector.set(active_display)
            self.config_selector.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="ew")

            # Delete button for user-imported configs
            if selected_conf_file and not self.config_manager.is_resistine_config(selected_conf_file):
                delete_btn = customtkinter.CTkButton(
                    selector_frame,
                    text="Delete",
                    width=70,
                    height=36,
                    corner_radius=8,
                    fg_color="#C5221F",
                    hover_color="#A01B18",
                    command=lambda: self._delete_config(selected_conf_file),
                )
                delete_btn.grid(row=0, column=2, padx=(0, 15), pady=10)

        # --- 3. Warning / Info Box ---
        warning_box = customtkinter.CTkFrame(scroll_frame, corner_radius=corner_radius, fg_color=warning_bg)
        warning_box.grid(row=2, column=0, sticky="ew", pady=5)

        warning_label = customtkinter.CTkLabel(
            warning_box,
            text=warning_text,
            text_color=warning_fg,
            font=customtkinter.CTkFont(size=14, weight="bold")
        )
        warning_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        # --- 4. System Information ---
        sys_info_data = self.get_system_info(selected_conf_file)

        sys_info_label = customtkinter.CTkLabel(scroll_frame, text="CURRENT VPN STATUS", font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"), text_color="#3a7ebf")
        sys_info_label.grid(row=3, column=0, sticky="w", pady=(15, 5))

        info_frame = customtkinter.CTkFrame(scroll_frame, corner_radius=corner_radius, fg_color=("#ffffff", "#141414"), border_width=1, border_color=("#dddddd", "#333333"))
        info_frame.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)

        row_num = 0
        for key, value in sys_info_data.items():
            key_label = customtkinter.CTkLabel(info_frame, text=f"{key}:", justify="left", text_color=("#666666", "#aaaaaa"))
            key_label.grid(row=row_num, column=0, padx=15, pady=5, sticky="w")

            value_label = customtkinter.CTkLabel(info_frame, text=value, justify="right", font=customtkinter.CTkFont(family="Inter", size=13, weight="bold"), text_color=("#000000", "#ffffff"))
            value_label.grid(row=row_num, column=1, padx=15, pady=5, sticky="e")
            row_num += 1

        # --- 5. Import Button ---
        import_button = customtkinter.CTkButton(
            scroll_frame,
            text="Import Configuration",
            command=self.import_config,
            fg_color="transparent",
            border_width=1,
            border_color=("#3a7ebf", "#1f538d"),
            text_color=("#3a7ebf", "#3a7ebf"),
            font=customtkinter.CTkFont(size=13)
        )
        import_button.grid(row=5, column=0, pady=20, sticky="ew")

        # Start polling for extension state changes (macOS only)
        if IS_MACOS:
            self._start_extension_polling()

        return self.main_container

    def _on_config_selected(self, display_name):
        """Handle config dropdown selection."""
        global my_vpn_status, active_client_name

        configs = self.config_manager.list_configs()
        selected = next((c for c in configs if c["display_name"] == display_name), None)
        if not selected:
            return

        new_config_name = selected["name"]
        current_active = self.config_manager.get_active_config_name()

        if new_config_name == current_active:
            return

        # Stop VPN if running on the old config
        if my_vpn_status == "Running" and active_client_name:
            old_path = os.path.join(wireguard_folder, f"{active_client_name}.conf")
            stop_vpn(old_path if not IS_WINDOWS else active_client_name)
            my_vpn_status = "Stopped"
            active_client_name = None

        self.config_manager.set_active_config(new_config_name)
        self.app.show_notification(f"Switched to {display_name}", type="info")
        self.update_plugin(self.id)

    def _delete_config(self, config_name):
        """Delete a user-imported config."""
        global my_vpn_status, active_client_name

        # Stop VPN if running on this config
        if my_vpn_status == "Running" and active_client_name == config_name:
            config_path = os.path.join(wireguard_folder, f"{config_name}.conf")
            stop_vpn(config_path if not IS_WINDOWS else config_name)
            my_vpn_status = "Stopped"
            active_client_name = None

        success, message = self.config_manager.delete_config(config_name)
        if success:
            self.app.show_notification("Configuration deleted", type="info")
        else:
            self.app.show_notification(f"Failed to delete: {message}", type="error")

        self.update_plugin(self.id)

    def _start_extension_polling(self):
        """Poll extension status every 5 seconds to detect enable/disable changes.
        macOS only — no-op on other platforms.
        """
        if not IS_MACOS:
            return
        self._stop_extension_polling()
        self._last_extension_state = is_extension_enabled()

        def poll():
            # Stop polling if the VPN page is no longer visible
            if not hasattr(self, 'main_container') or not self.main_container.winfo_exists():
                self._extension_poll_id = None
                return

            current_state = is_extension_enabled()
            if current_state != self._last_extension_state:
                logger.info(f"Extension state changed: {self._last_extension_state} -> {current_state}")
                self._last_extension_state = current_state
                self.update_plugin(self.id)
                return  # update_plugin rebuilds the screen which restarts polling

            self._extension_poll_id = self.app.after(5000, poll)

        self._extension_poll_id = self.app.after(5000, poll)

    def _stop_extension_polling(self):
        """Cancel any active extension polling."""
        if self._extension_poll_id:
            self.app.after_cancel(self._extension_poll_id)
            self._extension_poll_id = None

    def update_plugin(self, plugin_id):
        """Reloads the plugin UI to reflect state changes, but only if it's the active tab."""
        for plugin in self.app.plugin_list:
            if plugin.id == plugin_id:
                # ONLY grid if we are actually currently viewing this scale
                # This prevents "flashing" when status updates happen in the background
                current = getattr(self.app, "current_frame_name", "")
                target = f"frame_{plugin.get_name()}"
                
                if current == target:
                    if hasattr(self, 'main_container'):
                        try: self.main_container.destroy()
                        except: pass
                    plugin.create_main_screen().grid(row=0, column=1, sticky="nsew")
                return    

    def get_configuration_values(self, tunnel_name):
        
        conf_file_path = os.path.join(wireguard_folder, f"{tunnel_name}.conf")
        logger.info(f"Reading configuration from: {conf_file_path}")    
        data = {}

        if os.path.exists(conf_file_path):
            with open(conf_file_path, 'r') as conf_file:
                for line in conf_file:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        
                        if key == 'privatekey': data['private_key'] = value
                        elif key == 'address': data['client_ip_address'] = value
                        elif key == 'publickey': data['public_key'] = value
                        elif key == 'endpoint': 
                            data['endpoint'] = value
                            if ':' in value: data['port'] = value.split(':')[-1]
        elif not os.path.exists(wireguard_folder):
            logger.error(f"WireGuard configuration directory does not exist: {wireguard_folder}")
        else:
            logger.error(f"Configuration file not found: {conf_file_path}") 
        return data

    def activate_tunnel(self, tunnel_name):
        """
        Activates/Deactivates VPN tunnel.
        Handles MacOS specifically via helper functions.
        """
        logger.info(f"Toggling VPN tunnel: {tunnel_name}")
        global my_vpn_status, active_client_name
        
        if not tunnel_name:
            logger.error("❌ No tunnel name provided")
            self.app.show_notification("No tunnel name provided", type="error")
            return

        config_path = os.path.join(wireguard_folder, f"{tunnel_name}.conf")

        # --- MacOS Implementation ---
        if IS_MACOS:
            logger.info(f"macOS: Toggling {tunnel_name}")

            if not is_extension_enabled():
                logger.error("Network extension is disabled in System Settings")
                self.app.show_notification(
                    "VPN extension is disabled. Enable it in System Settings > "
                    "General > Login Items & Extensions > Network Extensions",
                    type="error",
                )
                my_vpn_status = "Stopped"
                active_client_name = None
                self.update_plugin(self.id)
                return

            if my_vpn_status == "Running":
                # STOP
                success = stop_vpn(config_path)
                if success:
                    my_vpn_status = "Stopped"
                    active_client_name = None
                    self.app.show_notification("VPN stopped", type="info")
                else:
                    logger.error("Failed to stop VPN")
                    self.app.show_notification("Failed to stop VPN", type="error")
            else:
                # START
                success = start_vpn(config_path)
                if success:
                    my_vpn_status = "Running"
                    active_client_name = tunnel_name
                    logger.info("✅ VPN started successfully")
                    self.app.show_notification("VPN started successfully", type="info")
                else:
                    logger.error("Failed to start VPN")
                    self.app.show_notification("Failed to start VPN", type="error")
            
            # Refresh UI
            self.update_plugin(self.id)

        # --- Linux Implementation ---
        elif IS_LINUX:
            logger.info(f"Linux: Toggling {tunnel_name}")
            
            if not check_wireguard_installed():
                logger.error("WireGuard tools not found.")
                self.app.show_notification("WireGuard tools not found", type="error")
                return

            if my_vpn_status == "Running":
                # STOP
                success = stop_vpn(config_path)
                if success:
                    my_vpn_status = "Stopped"
                    active_client_name = None
                    self.app.show_notification("VPN stopped", type="info")
                else:
                    logger.error("Failed to stop VPN")
                    self.app.show_notification("Failed to stop VPN", type="error")
            else:
                # START
                success = start_vpn(config_path)
                if success:
                    my_vpn_status = "Running"
                    active_client_name = tunnel_name
                    logger.info("✅ VPN started successfully")
                    self.app.show_notification("VPN started successfully", type="info")
                else:
                    logger.error("Failed to start VPN")
                    self.app.show_notification("Failed to start VPN", type="error")
            
            # Refresh UI
            self.update_plugin(self.id)

