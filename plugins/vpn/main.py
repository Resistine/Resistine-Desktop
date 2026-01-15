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
import tkinter as tk
import platform
import subprocess
import re
import sys
import ctypes
# --- Platform Specific Imports ---
# We assume these modules provide 'vpn_helper' and necessary logic
if platform.system() == "Windows":
    from plugins.vpn.wireguard.vpn_functions_windows import * 
    wireguard_folder = get_writable_wireguard_dir()
    
elif platform.system() == "Linux":
    from python_wireguard import Client, ServerConnection, Key
    from plugins.vpn.wireguard.vpn_functions_linux import *
    wireguard_folder = get_writable_wireguard_dir()

elif platform.system() == "Darwin":
    from plugins.vpn.wireguard.vpn_functions_darwin import *
    wireguard_folder = get_writable_wireguard_dir()
# DNS Configuration - Change this value to update DNS across the application
DNS_SERVER = "10.49.11.10"

# Global cache for interface mapping (e.g., config 'wg0' -> system 'utun3')
_interface_cache = {}
active_client_name = None
my_vpn_status = "Stopped"

# --- Initialization Logic ---
def initialize_vpn_status():
    global active_client_name, my_vpn_status, existing_interfaces

    existing_interfaces = []
    
    if platform.system() == "Windows":
        try:
            existing_interfaces = subprocess.run(['wg', 'show', 'interfaces'], capture_output=True, text=True, check=True).stdout.split()
        except:
            existing_interfaces = []
    elif platform.system() == "Linux" or platform.system() == "Darwin":
        try:
            existing_interfaces = os.popen('wg show interfaces').read().split()
        except:
            existing_interfaces = []

    # Check if any known interface is running
    # Note: DNS_SERVER is used as a test ping IP
    for interface in existing_interfaces:
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
            order=8,
            name="VPN",
            status=None, # Default status
            description="VPN Management",
            supported_systems=["Windows", "Darwin", "Linux"],
            translations={"US": "VPN", "ES": "VPN", "FR": "VPN"},
            icon_light_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "vpn_light.svg"),
            icon_dark_path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "vpn_dark.svg"),
        )
        self.app = app
        self.config_dir = wireguard_folder
        self.active_interface = None
        # Set status dynamically after super().__init__
        self.status = self.get_status()   

    def check_status(self):
        """Dynamic check of the VPN status."""
        if my_vpn_status == "Running":
            return "OK"
        elif my_vpn_status == "Connecting":
            return "Info"
        return "Warning"

    def get_selected_conf_file_name(self):
        """
        Get the single VPN config file from the wireguard directory.
        Since there's only one VPN config, we just find the first .conf file.
        """
        global active_client_name
        
        # 1. If VPN is running, return the running interface name
        if active_client_name and my_vpn_status == "Running":
            return active_client_name
        
        # 2. Find the single config file in wireguard directory
       
        if os.path.exists(wireguard_folder):
            conf_files = [f for f in os.listdir(wireguard_folder) if f.endswith('.conf')]
            if conf_files:
                # Use the first config file found (there should only be one)
                tunnel_name = os.path.splitext(conf_files[0])[0]
                self.current_selected_conf = tunnel_name
                return tunnel_name
            
        return None

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
            "System": f"{platform.system()} {platform.release()}"
        }

    def create_main_screen(self):
        """Create the main screen for the VPN plugin."""        
        return self.display_toggle_screen()   

    def toggle_vpn_connection(self, switch_value):
        """Handles the toggle switch.
        
        Args:
            switch_value: 1 for ON, 0 for OFF
        """
        selected_conf_file = self.get_selected_conf_file_name()

        if not selected_conf_file:
            logger.error("❌ Cannot toggle: No VPN config found in wireguard directory.")
            # Reset switch to off if no config available
            if hasattr(self, 'vpn_toggle_switch'):
                self.vpn_toggle_switch.deselect()
            return

        global my_vpn_status
        is_running = my_vpn_status == "Running"
        
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
            # This can happen if UI is out of sync - refresh to correct it
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
        is_connected = my_vpn_status == "Running"
        
        status_text = "Connected" if is_connected else "Disconnected"
        status_color = ("#1E8E3E", "#2CC985") if is_connected else ("#C5221F", "#FF474C")
        warning_text = "Your connection is secure" if is_connected else "Your connection is not secure"
        warning_bg = ("#E6F4EA", "#1E3A2F") if is_connected else ("#FDEDEC", "#3E2B2C")
        warning_fg = ("#1E8E3E", "#2CC985") if is_connected else ("#C5221F", "#FF474C")

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
            offvalue=0
        )
        if toggle_initial_value == 1:
            self.vpn_toggle_switch.select() 
        else:
            self.vpn_toggle_switch.deselect()
            
        self.vpn_toggle_switch.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")
        
        # --- 2. Warning / Info Box ---
        warning_box = customtkinter.CTkFrame(scroll_frame, corner_radius=corner_radius, fg_color=warning_bg)
        warning_box.grid(row=1, column=0, sticky="ew", pady=5)
        
        warning_label = customtkinter.CTkLabel(
            warning_box, 
            text=warning_text, 
            text_color=warning_fg,
            font=customtkinter.CTkFont(size=14, weight="bold")
        )
        warning_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        # --- 3. System Information ---
        sys_info_data = self.get_system_info(selected_conf_file)
        
        sys_info_label = customtkinter.CTkLabel(scroll_frame, text="CURRENT VPN STATUS", font=customtkinter.CTkFont(family="Inter", size=16, weight="bold"), text_color="#3a7ebf")
        sys_info_label.grid(row=2, column=0, sticky="w", pady=(15, 5))
        
        info_frame = customtkinter.CTkFrame(scroll_frame, corner_radius=corner_radius, fg_color=("#ffffff", "#141414"), border_width=1, border_color=("#dddddd", "#333333"))
        info_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)

        row_num = 0
        for key, value in sys_info_data.items():
            key_label = customtkinter.CTkLabel(info_frame, text=f"{key}:", justify="left", text_color=("#666666", "#aaaaaa"))
            key_label.grid(row=row_num, column=0, padx=15, pady=5, sticky="w")
            
            value_label = customtkinter.CTkLabel(info_frame, text=value, justify="right", font=customtkinter.CTkFont(family="Inter", size=13, weight="bold"), text_color=("#000000", "#ffffff"))
            value_label.grid(row=row_num, column=1, padx=15, pady=5, sticky="e")
            row_num += 1

        return self.main_container


    def update_plugin(self, plugin_id):
        """Reloads the plugin UI to reflect state changes."""
        for plugin in self.app.plugin_list:
            if plugin.id == plugin_id:
                if hasattr(self, 'main_container'):
                    self.main_container.destroy()
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
        if platform.system() == "Darwin":
            logger.info(f"MacOS: Toggling {tunnel_name}")
            
            
            if not check_wireguard_installed():
                logger.error("WireGuard tools not found.")
                self.app.show_notification("WireGuard tools not found", type="error")
                return

            if my_vpn_status == "Running":
                # STOP
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

        # --- Windows Implementation ---
        elif platform.system() == "Windows":
            #pass
            
            logger.info(f"Windows: Toggling {tunnel_name}")

            if my_vpn_status == "Running":
                success = stop_vpn(tunnel_name)
                if success:
                    my_vpn_status = "Stopped"
                    active_client_name = None
                    self.app.show_notification("VPN stopped", type="info")
                else:
                    self.app.show_notification("Failed to stop VPN", type="error")
                    logger.error("Failed to stop VPN")
            else:
                success = start_vpn(tunnel_name)
                if success:
                    my_vpn_status = "Running"
                    active_client_name = tunnel_name
                    self.app.show_notification("VPN started", type="info")
                else:
                    self.app.show_notification("Failed to start VPN", type="error")
                    logger.error("Failed to start VPN")

            self.update_plugin(self.id)

        # --- Linux Implementation ---
        elif platform.system() == "Linux":
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




